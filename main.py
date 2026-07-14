import os
import functions_framework
import google.auth
from google.cloud import bigquery
from google.ads.googleads.client import GoogleAdsClient
from google.api_core import protobuf_helpers

PROJECT_ID = "dt-dertour-digital-marketing"
VIEW = f"{PROJECT_ID}.sea_automation_prod.dertour_adgroup-sync_actions"

# DRY_RUN=true  -> nur log
# DRY_RUN=false -> Aenderung
DRY_RUN = os.environ.get("DRY_RUN", "true").lower() != "false"

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/cloud-platform",
]


def get_decisions():
    """Read BQ view."""
    credentials, _ = google.auth.default(scopes=SCOPES)
    client = bigquery.Client(project=PROJECT_ID, credentials=credentials)
    query = f"""
        SELECT adgroup_id, customer_id, action
        FROM `{VIEW}`
        WHERE action IN ('ENABLE', 'PAUSE')
    """
    return list(client.query(query).result())


def build_ads_client():
    """secret manager data"""
    config = {
        "developer_token": os.environ["GOOGLE_ADS_DEVELOPER_TOKEN"],
        "client_id": os.environ["GOOGLE_ADS_CLIENT_ID"],
        "client_secret": os.environ["GOOGLE_ADS_CLIENT_SECRET"],
        "refresh_token": os.environ["GOOGLE_ADS_REFRESH_TOKEN"],
        "login_customer_id": os.environ["GOOGLE_ADS_LOGIN_CUSTOMER_ID"],
        "use_proto_plus": True,
    }
    return GoogleAdsClient.load_from_dict(config)


def apply_change(ads_client, customer_id, ad_group_id, action):
    """adgroup sync logic based on BQ view."""
    service = ads_client.get_service("AdGroupService")
    operation = ads_client.get_type("AdGroupOperation")
    ad_group = operation.update
    ad_group.resource_name = service.ad_group_path(customer_id, ad_group_id)
    ad_group.status = (
        ads_client.enums.AdGroupStatusEnum.ENABLED
        if action == "ENABLE"
        else ads_client.enums.AdGroupStatusEnum.PAUSED
    )
    ads_client.copy_from(
        operation.update_mask,
        protobuf_helpers.field_mask(None, ad_group._pb),
    )
    service.mutate_ad_groups(customer_id=customer_id, operations=[operation])


@functions_framework.http
def sync_adgroups(request):
    decisions = get_decisions()
    print(f"{len(decisions)} Anzeigengruppe(n) zu aendern. DRY_RUN={DRY_RUN}")

    if not decisions:
        return "Keine Aenderungen noetig.", 200

    ads_client = None if DRY_RUN else build_ads_client()

    done = 0
    for row in decisions:
        info = f"{row.action}: adgroup {row.adgroup_id} (Konto {row.customer_id})"
        if DRY_RUN:
            print(f"[DRY_RUN] wuerde tun -> {info}")
        else:
            apply_change(ads_client, row.customer_id, row.adgroup_id, row.action)
            print(f"[LIVE] erledigt -> {info}")
            done += 1

    msg = f"Fertig. {len(decisions)} geprueft, {done} geaendert (DRY_RUN={DRY_RUN})."
    print(msg)
    return msg, 200
