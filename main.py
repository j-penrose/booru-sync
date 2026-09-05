import argparse
import logging
import time
from collections import defaultdict
from collections.abc import Callable
from contextlib import nullcontext
from io import BytesIO
from typing import Any, BinaryIO, Literal, NamedTuple

import requests

DANBOORU_TEST_URL = "https://testbooru.donmai.us"
DANBOORU_PROD_URL = "https://danbooru.donmai.us"

USER_AGENT = "danbooru-sync/1.0"

DANBOORU_TAG_CATEGORIES = {0: "general", 1: "artist", 3: "copyright", 4: "character", 5: "meta"}

logger = logging.getLogger(__name__)


class Args(NamedTuple):
    danbooru_user_id: int
    blombooru_base_url: str
    blomboru_api_key: str
    log_level: str


class Tag(NamedTuple):
    name: str
    category_id: int


class TagImplication(NamedTuple):
    antecedent: str
    consequent: str


class RateLimiter:
    def __init__(self, limit: float) -> None:
        self._last_request: float = 0
        self._limit: float = limit

    def __enter__(self):
        elapsed = time.time() - self._last_request
        if elapsed < self._limit:
            time.sleep(self._limit - elapsed)

    def __exit__(self, exc_type, exc, tb):
        self._last_request = time.time()


def request(
    method: Literal["GET", "POST"],
    url: str,
    *,
    json_: dict | None = None,
    files: Any | None = None,
    session: requests.Session | None = None,
    rate_limiter: RateLimiter | None = None,
) -> requests.Response:
    requester = session or requests
    with rate_limiter or nullcontext():
        response = requester.request(method, url, json=json_, files=files)
        logger.debug(f"[{response.status_code}] {method} {url}")
        return response


def create_danbooru_url(base_url: str, json_: str, limit, page, **search: str) -> str:
    search_str = "&".join(f"search[{key}]={value}" for key, value in search.items())
    return f"{base_url}/{json_}?limit={limit}&page={page}&{search_str}"


def fetch_danbooru_resource(
    *,
    session: requests.Session,
    rate_limiter: RateLimiter,
    json_: str,
    early_stopper: Callable[[dict], bool],
    **search_params: str,
) -> list[dict]:
    result: list[dict] = []  # id, tag

    page: int = 0
    limit = 1000
    continue_ = True

    while continue_:
        url = create_danbooru_url(DANBOORU_PROD_URL, json_, limit=limit, page=page, **search_params)
        resp = request("GET", url, session=session, rate_limiter=rate_limiter)
        data = resp.json()

        if not len(data):
            break

        for entry in data:
            if early_stopper(entry):
                continue_ = False
                break
            result.append(entry)
        page += 1
    return result


def fetch_danbooru_tags(session: requests.Session, rate_limiter: RateLimiter, min_post_count: int = 25) -> list[Tag]:
    data = fetch_danbooru_resource(
        session=session,
        rate_limiter=rate_limiter,
        json_="tags.json",
        early_stopper=lambda entry: entry["post_count"] < min_post_count,
        hide_empty="yes",
        is_deprecated="no",
        order="count",
    )
    return [Tag(entry["name"], entry["category"]) for entry in data]


def fetch_danbooru_tag_implications(
    session: requests.Session, rate_limiter: RateLimiter, min_post_count: int = 25
) -> list[TagImplication]:
    data = fetch_danbooru_resource(
        session=session,
        rate_limiter=rate_limiter,
        json_="tag_implications.json",
        early_stopper=lambda entry: False,
        order="tag_count",
    )
    return [TagImplication(entry["antecedent_name"], entry["consequent_name"]) for entry in data]


def fetch_danbooru_tag_aliases(session: requests.Session, rate_limiter: RateLimiter) -> list[TagImplication]:
    data = fetch_danbooru_resource(
        session=session,
        rate_limiter=rate_limiter,
        json_="tag_aliases.json",
        early_stopper=lambda entry: False,
    )
    return [TagImplication(entry["antecedent_name"], entry["consequent_name"]) for entry in data]


def create_blombooru_tags(session: requests.Session, base_url: str, danbooru_csv: BinaryIO) -> True:
    resp = request(
        "POST", f"{base_url.rstrip('/')}/api/admin/import-tags-csv", files={"file": danbooru_csv}, session=session
    )
    data = resp.json()
    if not resp.ok:
        logger.warning("failed to create tags")
        return False
    logger.debug(f"{data}")
    logger.info(
        f"created tags={data['tags_created']} "
        f"updated tags={data['tags_updated']}, "
        f"created aliases={data['aliases_created']}"
    )
    return True


def create_blombooru_implications(session: requests.Session, base_url: str, implications: dict[str, set[str]]) -> bool:
    ok_count = 0
    for target, imps in implications.items():
        resp = request(
            "POST",
            f"{base_url.rstrip('/')}/api/tag-implications/",
            json_={"target_tags": [target], "implied_tags": list(imps)},
            session=session,
        )
        if not resp.ok:
            logger.warning(f"failed to create tag implication: {target} -> {imps}")
            continue
        ok_count += 1
    logger.info(f"implications created={ok_count}")
    return True


def get_blombooru_implications(session: requests.Session, base_url) -> dict[str, set[str]]:
    resp = request("GET", f"{base_url.rstrip('/')}/api/tag-implications/", session=session)
    data = resp.json()

    imps: dict[str, set[str]] = {}
    for imp in data:
        if not imp["target_tags"] or len(imp["target_tags"]) > 1:
            continue
        imps[imp["target_tags"][0]["name"]] = {tag["name"] for tag in imp["implied_tags"]}
    return imps


def parse_args() -> Args:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dbr-user-id", type=str, required=True, help="Your danbooru user id")
    parser.add_argument("--bb-base-url", type=str, required=True, help="Base url where blombooru is hosted")
    parser.add_argument("--bb-api-key", type=str, required=True, help="API key for blombooru admin account")
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=("DEBUG", "INFOR", "WARNING", "ERROR"),
        help="Minimum log level to show",
    )
    args = parser.parse_args()
    return Args(
        args.dbr_user_id, args.bb_base_url, f"blom_{args.bb_api_key.lstrip('blom_')}", getattr(logging, args.log_level)
    )


def sync(danbooru_user_id: int, blombooru_api_key: str, blombooru_base_url: str, min_post_count: int) -> None:
    with requests.Session() as session:
        session.verify = False
        requests.packages.urllib3.disable_warnings()

        session.get(blombooru_base_url)
        session.headers.update({"User-Agent": f"{USER_AGENT} (user #{danbooru_user_id})"})

        rate_limiter = RateLimiter(1)
        dbr_tags = fetch_danbooru_tags(session, rate_limiter, min_post_count=min_post_count)
        tag_set: set[str] = {tag.name for tag in dbr_tags}

        dbr_aliases = fetch_danbooru_tag_aliases(session, rate_limiter)
        final_aliases: dict[str, set[str]] = defaultdict(set)
        for alias in dbr_aliases:
            if alias.antecedent in tag_set and alias.consequent in tag_set:
                final_aliases[alias.consequent].add(alias.antecedent)

        dbr_imps = fetch_danbooru_tag_implications(session, rate_limiter)
        prelim_imps: dict[str, set[str]] = defaultdict(set)
        for imp in dbr_imps:
            if imp.antecedent in tag_set and imp.consequent in tag_set:
                prelim_imps[imp.antecedent].add(imp.consequent)

        # create a csv buffer: name, category_id, post_count (ignore this since blombooru does), aliases
        buffer = BytesIO()
        for tag in dbr_tags:
            aliases_str = ",".join(final_aliases[tag.name])
            buffer.write(f'{tag.name},{tag.category_id},0,"{aliases_str}"\n'.encode())
        buffer.seek(0)

        # setup session authentication for blombooru instance
        session.cookies.update({"admin_mode": "true", "admin_token": blombooru_api_key})
        create_blombooru_tags(session, blombooru_base_url, danbooru_csv=buffer)

        # filter out already existing implications
        bb_imps = get_blombooru_implications(session, blombooru_base_url)
        final_imps = {k: v for k, v in prelim_imps.items() if k not in bb_imps or bb_imps[k] != v}
        create_blombooru_implications(session, blombooru_base_url, final_imps)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--danbooru-user-id",
        type=str,
        required=True,
        help="Your Danbooru user id (can be found under your profile page)",
    )
    parser.add_argument(
        "--blombooru-api-key", type=str, required=True, help="Blombooru API key, must have admin access"
    )
    parser.add_argument(
        "--blombooru-base-url",
        type=str,
        required=True,
        help="The base url of your Blombooru instance e.g. http://my.blombooru.instance:1234",
    )
    parser.add_argument(
        "--min-post-count",
        type=str,
        default=25,
        help="A tag on Danbooru must have been used on at least this many posts to be synced",
    )
    parser.add_argument("--log-level", choices=("DEBUG", "INFO", "WARNING", "ERROR"), default="DEBUG")
    args = parser.parse_args()

    logging.basicConfig(level=getattr(logging, args.log_level))
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    sync(args.danbooru_user_id, args.blombooru_api_key, args.blombooru_base_url, args.min_post_count)


if __name__ == "__main__":
    main()
