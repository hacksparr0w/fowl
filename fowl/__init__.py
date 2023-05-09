import aiohttp
import json
import re
import time

from http import HTTPStatus
from http.cookies import SimpleCookie
from typing import Optional

from bs4 import BeautifulSoup


TWITTER_AUTH_TOKEN_PATTERN = re.compile(r"\"([a-zA-Z0-9%]{104})\"")
TWITTER_METADATA_PATTERN = re.compile(r"window\.__META_DATA__=(\{.+?\});")
TWITTER_GUEST_TOKEN_COOKIE_PATTERN = re.compile(
    r"document\.cookie=\"(gt=.+?)\";"
)


def _validate_status(
        response: aiohttp.ClientResponse,
        status: Optional[int] = HTTPStatus.OK
) -> None:
    if response.status != status:
        raise ValueError


async def _get_json(session, *args, **kwargs) -> dict:
    async with session.get(*args, **kwargs) as response:
        _validate_status(response)

        return await response.json()


class TwitterApi:
    URL = "https://api.twitter.com/1.1"

    @classmethod
    def client_event(cls, cookie_fetch_time: int) -> tuple[str, dict]:
        url = f"{cls.URL}/jot/client_event.json"

        event_value = int(time.time() * 1000) - cookie_fetch_time
        data = {
            "category": "perftown",
            "log": json.dumps([{
                "description": "rweb:cookiesMetadata:load",
                "product": "rweb",
                "event_value": event_value
            }])
        }

        return url, data


class TwitterWebapp:
    URL = "https://twitter.com"


class TwitterGraphQl:
    URL = "https://twitter.com/i/api/graphql"

    @staticmethod
    def _to_http_params(variables: dict, features: dict) -> str:
        return {
            "variables": json.dumps(variables),
            "features": json.dumps(features)
        }

    @classmethod
    def user_by_username(cls, username: str) -> tuple[str, dict, dict]:
        url = f"{cls.URL}/pVrmNaXcxPjisIvKtLDMEA/UserByScreenName"
        variables = {
            "screen_name": username
        }

        features = {
            "blue_business_profile_image_shape_enabled": True,
            "responsive_web_graphql_exclude_directive_enabled": True,
            "verified_phone_label_enabled": False,
            "highlights_tweets_tab_ui_enabled": False,
            "creator_subscriptions_tweet_preview_api_enabled": False,
            "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
            "responsive_web_graphql_timeline_navigation_enabled": True
        }

        params = cls._to_http_params(variables, features)

        return url, params

    @classmethod
    def tweets(
            cls,
            user_id: str,
            count: Optional[int] = None,
            cursor: Optional[str] = None
    ) -> tuple[str, dict, dict]:
        url = f"{cls.URL}/WzJjibAcDa-oCjCcLOotcg/UserTweets"
        variables = {
            "userId": user_id,
            "count": count or 40,
            "includePromotedContent": True,
            "withQuickPromoteEligibilityTweetFields": True,
            "withVoice": True,
            "withV2Timeline": True
        }

        if cursor:
            variables["cursor"] = cursor

        features = {
            "rweb_lists_timeline_redesign_enabled": False,
            "blue_business_profile_image_shape_enabled": True,
            "responsive_web_graphql_exclude_directive_enabled": True,
            "verified_phone_label_enabled": False,
            "creator_subscriptions_tweet_preview_api_enabled": False,
            "responsive_web_graphql_timeline_navigation_enabled": True,
            "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
            "tweetypie_unmention_optimization_enabled": True,
            "vibe_api_enabled": True,
            "responsive_web_edit_tweet_api_enabled": True,
            "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
            "view_counts_everywhere_api_enabled": True,
            "longform_notetweets_consumption_enabled": True,
            "tweet_awards_web_tipping_enabled": False,
            "freedom_of_speech_not_reach_fetch_enabled": True,
            "standardized_nudges_misinfo": True,
            "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": False,
            "interactive_text_enabled": True,
            "responsive_web_text_conversations_enabled": False,
            "longform_notetweets_rich_text_read_enabled": True,
            "longform_notetweets_inline_media_enabled": False,
            "responsive_web_enhance_cards_enabled": False
        }

        params = cls._to_http_params(variables, features)

        return url, params


def _build_headers(auth_token: str, guest_token: str) -> dict:
    return {
        "Authorization": f"Bearer {auth_token}",
        "x-guest-token": guest_token
    }


def _parse_app_data(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    elements = soup.find_all("script")

    url = None
    metadata = None
    guest_token = None

    for element in elements:
        src = element.get("src")
        text = element.text

        metadata_match = TWITTER_METADATA_PATTERN.search(text)
        guest_token_cookie_match = TWITTER_GUEST_TOKEN_COOKIE_PATTERN.search(
            text
        )

        if src and "main" in src:
            url = src
        elif metadata_match:
            metadata = json.loads(metadata_match.group(1))
        elif guest_token_cookie_match:
            guest_token_cookie = SimpleCookie()
            guest_token_cookie.load(guest_token_cookie_match.group(1))
            guest_token = guest_token_cookie.get("gt").value

    if not url or not metadata or not guest_token:
        raise ValueError

    return url, metadata, guest_token


def _parse_auth_token(source: str) -> str:
    match = TWITTER_AUTH_TOKEN_PATTERN.search(source)

    if not match:
        raise ValueError

    return match.group(1)


def _parse_user(data: dict) -> dict:
    return data["data"]["user"]["result"]


def _parse_tweet_cursor(cursor: dict) -> str:
    return cursor["content"]["value"]


def _parse_tweets(data: dict) -> dict:
    timeline = data["data"]["user"]["result"]["timeline_v2"]["timeline"]
    instructions = timeline["instructions"]

    entries = []

    for instruction in instructions:
        if instruction["type"] == "TimelineAddEntries":
            entries = instruction["entries"]
            cursors = entries[-2:]
            entries = entries[:-2]

    cursor_top = _parse_tweet_cursor(cursors[0])
    cursor_bottom = _parse_tweet_cursor(cursors[1])

    return entries, cursor_top, cursor_bottom


async def register(session):
    index_source = None
    app_source = None

    async with session.get(TwitterWebapp.URL) as response:
        _validate_status(response)
        index_source = await response.text()

    app_url, metadata, guest_token = _parse_app_data(index_source)
    cookie_fetch_time = metadata["cookies"]["fetchedTime"]

    async with session.get(app_url) as response:
        _validate_status(response)
        app_source = await response.text()

    auth_token = _parse_auth_token(app_source)
    session.headers.update(_build_headers(auth_token, guest_token))
    endpoint_url, data = TwitterApi.client_event(cookie_fetch_time)

    async with session.post(endpoint_url, data=data) as response:
        _validate_status(response)


async def get_user_by_username(session, username: str) -> dict:
    url, params = TwitterGraphQl.user_by_username(username)

    return _parse_user(await _get_json(session, url, params=params))


async def get_tweets(
        session,
        user_id: str,
        count: Optional[int] = None,
        cursor: Optional[str] = None
) -> dict:
    url, params = TwitterGraphQl.tweets(user_id, count, cursor)

    return _parse_tweets(await _get_json(session, url, params=params))
