from urllib.parse import urlsplit

from adrobot.keitaro.client import KeitaroClient, KeitaroError


def _parse_domain_host(value: str) -> str:
    value = value.strip()
    if not value.startswith("//") and "://" not in value:
        value = "//" + value
    try:
        return (urlsplit(value).hostname or "").rstrip(".")
    except ValueError:
        return ""


def _resolve_resource_id(keitaro: KeitaroClient, path: str, name: str) -> int:
    resources = keitaro.request_json("GET", path)
    if not isinstance(resources, list):
        raise KeitaroError(f"Expected a list from Keitaro at {path}")

    available = [
        resource
        for resource in resources
        if isinstance(resource, dict)
        and isinstance(resource.get("name"), str)
        and resource.get("state") != "deleted"
    ]
    if path == "domains":
        target = _parse_domain_host(name)
        if not target:
            raise KeitaroError(
                "Некорректный домен кампании. Проверьте настройки домена."
            )
        matches = [
            resource.get("id")
            for resource in available
            if _parse_domain_host(resource["name"]) == target
        ]
        if not matches:
            raise KeitaroError(
                f"Домен {target} не найден. Проверьте домен кампании в Keitaro."
            )
    else:
        matches = [
            resource.get("id") for resource in available if resource["name"] == name
        ]
    if len(matches) != 1 or type(matches[0]) is not int or matches[0] <= 0:
        raise KeitaroError(f"Expected one matching Keitaro resource at {path}: {name}")
    return matches[0]


def resolve_campaign_group_id(keitaro: KeitaroClient, name: str) -> int:
    return _resolve_resource_id(keitaro, "groups?type=campaigns", name)


def resolve_traffic_source_id(keitaro: KeitaroClient, name: str) -> int:
    return _resolve_resource_id(keitaro, "traffic_sources", name)


def resolve_campaign_domain_id(
    keitaro: KeitaroClient, domain_id: int | None, domain_name: str
) -> int:
    if domain_id is None:
        return _resolve_resource_id(keitaro, "domains", domain_name)

    try:
        domain = keitaro.request_json("GET", f"domains/{domain_id}")
    except KeitaroError as exc:
        if exc.status_code == 404:
            raise KeitaroError(f"Домен #{domain_id} не найден в Keitaro.") from exc
        raise
    if (
        not isinstance(domain, dict)
        or type(domain.get("id")) is not int
        or domain["id"] != domain_id
        or domain.get("state") != "active"
    ):
        raise KeitaroError(f"Keitaro не подтвердил, что домен #{domain_id} активен.")
    return domain_id
