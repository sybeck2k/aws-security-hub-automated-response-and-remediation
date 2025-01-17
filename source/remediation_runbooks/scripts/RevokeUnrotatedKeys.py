#!/usr/bin/python
###############################################################################
#  Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.         #
#                                                                             #
#  Licensed under the Apache License Version 2.0 (the "License"). You may not #
#  use this file except in compliance with the License. A copy of the License #
#  is located at                                                              #
#                                                                             #
#      http://www.apache.org/licenses/LICENSE-2.0/                            #
#                                                                             #
#  or in the "license" file accompanying this file. This file is distributed  #
#  on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, express #
#  or implied. See the License for the specific language governing permis-    #
#  sions and limitations under the License.                                   #
###############################################################################
from datetime import datetime
from datetime import timedelta
import boto3
from botocore.config import Config

boto_config = Config(
    retries ={
        'mode': 'standard'
    }
)

responses = {}
responses["DeactivateUnusedKeysResponse"] = []

def str_time_to_datetime(dt_str):
    dt_obj = datetime.strptime(dt_str, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=None)
    return dt_obj

def connect_to_iam(boto_config):
    return boto3.client('iam', config=boto_config)

def connect_to_config(boto_config):
    return boto3.client('config', config=boto_config)

def get_user_name(resource_id):
    config_client = connect_to_config(boto_config)
    list_discovered_resources_response = config_client.list_discovered_resources(
        resourceType='AWS::IAM::User',
        resourceIds=[resource_id]
    )
    resource_name = list_discovered_resources_response.get("resourceIdentifiers")[0].get("resourceName")
    return resource_name

def list_access_keys(user_name, include_inactive=False):
    iam_client = connect_to_iam(boto_config)
    active_keys = []
    keys = iam_client.list_access_keys(UserName=user_name).get("AccessKeyMetadata", [])
    for key in keys:
        if include_inactive or key.get('Status') == 'Active':
            active_keys.append(key)
    return active_keys

def deactivate_unused_keys(access_keys, max_credential_usage_age, user_name):
    iam_client = connect_to_iam(boto_config)
    for key in access_keys:
        print(key)
        last_used = iam_client.get_access_key_last_used(AccessKeyId=key.get("AccessKeyId")).get("AccessKeyLastUsed")
        deactivate = False
        
        days_since_creation = (datetime.now() - str_time_to_datetime(key.get("CreateDate"))).days
        last_used_days = (datetime.now() - str_time_to_datetime(last_used.get("LastUsedDate"))).days

        print(f'Key {key.get("AccessKeyId")} is {days_since_creation} days old and last used {last_used_days} days ago')

        if days_since_creation > max_credential_usage_age:
            deactivate = True
        
        if last_used_days > max_credential_usage_age:
            deactivate = True

        if deactivate:
            deactivate_key(user_name, key.get("AccessKeyId"))

def deactivate_key(user_name, access_key):
    iam_client = connect_to_iam(boto_config)
    responses["DeactivateUnusedKeysResponse"].append({"AccessKeyId": access_key, "Response": iam_client.update_access_key(UserName=user_name, AccessKeyId=access_key, Status="Inactive")})

def verify_expired_credentials_revoked(responses, user_name):
    if responses.get("DeactivateUnusedKeysResponse"):
        for key in responses.get("DeactivateUnusedKeysResponse"):
            key_data = next(filter(lambda x: x.get("AccessKeyId") == key.get("AccessKeyId"), list_access_keys(user_name, True)))
            if key_data.get("Status") != "Inactive":
                error_message = "VERIFICATION FAILED. ACCESS KEY {} NOT DEACTIVATED".format(key_data.get("AccessKeyId"))
                raise Exception(error_message)
   
    return {
        "output": "Verification of unrotated access keys is successful.",
        "http_responses": responses
    }

def unrotated_key_handler(event, context):
    user_name = get_user_name(event.get("IAMResourceId"))
    max_credential_usage_age = int(event.get("MaxCredentialUsageAge"))
    access_keys = list_access_keys(user_name)
    deactivate_unused_keys(access_keys, max_credential_usage_age, user_name)
    return verify_expired_credentials_revoked(responses, user_name)
