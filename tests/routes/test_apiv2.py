from typing import Dict

import jwt
import json

from unittest import TestCase
from unittest.mock import patch, NonCallableMock

from flask import Response
from requests.models import Response as RequestsResponse
from requests.structures import CaseInsensitiveDict
from responses import RequestsMock

from hollowman.app import application
from hollowman import conf
from hollowman.auth.jwt import jwt_auth
from tests import rebuild_schema
from tests.utils import with_json_fixture

from hollowman.models import HollowmanSession, User, Account


class TestAuthentication(TestCase):
    def setUp(self):
        rebuild_schema()
        self.session = HollowmanSession()

        self.new_dispatcher_user = User(
            tx_email="xablau@host.com.br",
            tx_name="Xablau",
            tx_authkey="69ed620926be4067a36402c3f7e9ddf0")
        self.normal_user = User(
            tx_email="user@host.com.br",
            tx_name="John Doe",
            tx_authkey="70ed620926be4067a36402c3f7e9ddf0")
        self.normal_user.accounts = [Account(name="New Account", namespace="acc", owner="company")]
        self.session.add_all([self.new_dispatcher_user, self.normal_user])
        self.session.commit()

        self.response_http_200 = Response(status=200)

    def tearDown(self):
        patch.stopall()

    def make_auth_header(self, email: str) -> Dict[str, str]:
        jwt_token = jwt_auth.jwt_encode_callback({"email": email, "account_id": 1})
        return {
            "Authorization": "JWT {}".format(jwt_token.decode('utf-8'))
        }

    @with_json_fixture("single_full_app.json")
    def test_it_creates_a_response_using_a_dict_of_headers(self, fixture):
        """
        O atributo headers de um objeto `request.models.Response` é utilizado
        para gerar o response do holloman. Por ser do tipo `CaseInsentiveDict`,
        quebra a implementação do flask e faz com que seja necessário o typecast
        para `dict`.
        """
        with patch('hollowman.request_handlers.upstream.replay_request') as replay_request:
            response = NonCallableMock(
                content=b"Foo",
                status_code=200,
                headers=CaseInsensitiveDict({'dog': 'Xablau'})
            )
            replay_request.return_value = response
            test_client = application.test_client()
            with application.app_context():
                auth_header = self.make_auth_header(self.normal_user.tx_email)
                with RequestsMock() as rsps:
                    rsps.add(method='GET',
                             url=conf.MARATHON_ENDPOINT + '/v2/apps',
                             body=json.dumps({'apps': [fixture]}),
                             status=200)
                    r = test_client.get("/v2/apps", headers=auth_header)

                    self.assertEqual(200, r.status_code)
