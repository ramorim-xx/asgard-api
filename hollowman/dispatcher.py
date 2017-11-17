from typing import Iterable
from flask import Response as FlaskResponse, request
import json

from hollowman.filters.basicconstraint import BasicConstraintFilter
from marathon.models import MarathonDeployment

from hollowman.marathonapp import SieveMarathonApp

from hollowman.filters.trim import TrimRequestFilter
from hollowman.filters.forcepull import ForcePullFilter
from hollowman.filters.appname import AddAppNameFilter
from hollowman.filters.namespace import NameSpaceFilter
from hollowman.hollowman_flask import OperationType, FilterType
from hollowman.filters.owner import AddOwnerConstraintFilter
from hollowman.filters.defaultscale import DefaultScaleFilter
from hollowman.http_wrappers.response import Response


FILTERS_PIPELINE = {
    FilterType.REQUEST: {
        OperationType.READ: (
        ),

        OperationType.WRITE: (
            DefaultScaleFilter(),
            NameSpaceFilter(),
            ForcePullFilter(),
            TrimRequestFilter(),
            AddAppNameFilter(),
            BasicConstraintFilter(),
            AddOwnerConstraintFilter(),
        )
    },
    FilterType.RESPONSE: (
        AddAppNameFilter(),
        NameSpaceFilter(),
    )
}

# Keys que são multi-valor e que devem
# ser mergeados de forma especial quando
# juntamos a request_app com a original_app
REMOVABLE_KEYS = {
    "constraints": [],
    "labels": {},
    "env": {},
    "healthChecks": [],
    "upgradeStrategy": None,
}

def dispatch(operations, user, request_app, app,
             filters_pipeline=FILTERS_PIPELINE[FilterType.REQUEST]) -> SieveMarathonApp:
    """
    :type operations: Iterable[OperationType]
    :type request_app: MarathonApp
    :type app: MarathonApp
    :type filters_pipeline: Dict[OperationType, Iterable[BaseFilter]]

    todo: (user, request_app, app) podem ser refatorados em uma classe de domínio
    """
    merged_app = merge_marathon_apps(base_app=app, modified_app=request_app)
    for operation in operations:
        for filter_ in filters_pipeline[operation]:
            func = getattr(filter_, operation.value)
            merged_app = func(user, merged_app, app)

    return merged_app


def dispatch_response_pipeline(user, response: Response, filters_pipeline=FILTERS_PIPELINE[FilterType.RESPONSE]) -> FlaskResponse:
    if response.is_app_request():
        filtered_response_apps = []
        for response_app, original_app in response.split():
            filtered_app = response_app
            for filter_ in filters_pipeline:
                filtered_app = filter_.response(user, filtered_app, original_app)

            #if user:
            #    if original_app.id.startswith("/{}/".format(user.current_account.namespace)):
            #        filtered_response_apps.append((filtered_app, original_app))
            #else:
            #    filtered_response_apps.append((filtered_app, original_app))
            filtered_response_apps.append((filtered_app, original_app))
        return response.join(filtered_response_apps)
    elif response.is_group_request():
        filtered_response_groups = []
        for response_group, original_group in response.split():
            filtered_group = response_group
            for filter_ in filters_pipeline:
                if hasattr(filter_, "response_group"):
                    filtered_group = filter_.response_group(user, filtered_group, original_group)
            filtered_response_groups.append((filtered_group, original_group))
        return response.join(filtered_response_groups)
    elif response.is_deployment():
        content = json.loads(response.response.data)
        deployments = (MarathonDeployment.from_json(deploy) for deploy in content)

        filtered_deployments = []
        for deployment in deployments:
            for filter_ in filters_pipeline:
                if hasattr(filter_, "response_deployment"):
                    filter_.response_deployment(user, deployment)
            filtered_deployments.append(deployment)

        return FlaskResponse(
            response=json.dumps(filtered_deployments, cls=Response.json_encoder),
            status=response.response.status,
            headers=response.response.headers
        )


def merge_marathon_apps(base_app, modified_app):
    merged = base_app.json_repr(minimal=False)
    merged.update(modified_app.json_repr(minimal=True))
    try:
        raw_request_data = json.loads(request.data)
        for key, _ in REMOVABLE_KEYS.items():
            if key in raw_request_data:
                merged[key] = raw_request_data[key]
    except Exception as e:
        pass
    return SieveMarathonApp.from_json(merged)

