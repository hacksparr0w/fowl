import json
import re

from dataclasses import dataclass
from enum import Enum, auto
from http import HTTPStatus
from http.cookies import SimpleCookie
from typing import Any, Optional

import aiohttp

from bs4 import BeautifulSoup


TWITTER_AUTH_TOKEN_PATTERN = re.compile(r"\"([a-zA-Z0-9%]{104})\"")
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
    def user_by_handle(cls, handle: str) -> tuple[str, dict, dict]:
        url = f"{cls.URL}/pVrmNaXcxPjisIvKtLDMEA/UserByScreenName"
        variables = {
            "screen_name": handle
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
    def timeline(
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


@dataclass
class TwitterUser:
    rest_id: str
    handle: str
    name: str
    description: str


@dataclass
class Tweet:
    content: Optional[str]
    child: Optional["Tweet"] = None


class TimelineEntryType(Enum):
    PINNED_TWEET = auto()
    STATUS_TWEET = auto()


@dataclass
class TimelineEntry:
    type: TimelineEntryType
    tweet: Tweet


def _build_headers(auth_token: str, guest_token: str) -> dict:
    return {
        "Authorization": f"Bearer {auth_token}",
        "x-guest-token": guest_token
    }


def _parse_app_data(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    elements = soup.find_all("script")

    url = None
    guest_token = None

    for element in elements:
        src = element.get("src")
        text = element.text

        guest_token_cookie_match = TWITTER_GUEST_TOKEN_COOKIE_PATTERN.search(
            text
        )

        if src and "main" in src:
            url = src
        elif guest_token_cookie_match:
            guest_token_cookie = SimpleCookie()
            guest_token_cookie.load(guest_token_cookie_match.group(1))
            guest_token = guest_token_cookie.get("gt").value

    if not url or not guest_token:
        raise ValueError

    return url, guest_token


def _parse_auth_token(source: str) -> str:
    match = TWITTER_AUTH_TOKEN_PATTERN.search(source)

    if not match:
        raise ValueError

    return match.group(1)


def _parse_user(data: dict) -> TwitterUser:
    result = data["data"]["user"]["result"]

    rest_id = result["rest_id"]
    legacy = result["legacy"]
    handle = legacy["screen_name"]
    name = legacy["name"]
    description = legacy["description"]

    return TwitterUser(
        rest_id=rest_id,
        handle=handle,
        name=name,
        description=description
    )


def _parse_tweet(data: dict) -> Tweet:
    legacy = data["legacy"]
    content = legacy["full_text"]
    child = None

    if "retweeted_status_result" in legacy:
        child = _parse_tweet(legacy["retweeted_status_result"]["result"])
        content = None
    elif "quoted_status_result" in data:
        child = _parse_tweet(data["quoted_status_result"]["result"])

    return Tweet(content, child)


def _parse_timeline_tweet_entry(
    data: dict,
    type: TimelineEntryType
) -> TimelineEntry:
    tweet = _parse_tweet(
        data["content"]["itemContent"]["tweet_results"]["result"]
    )

    return TimelineEntry(type, tweet)


def _parse_tweet_cursor(cursor: dict) -> str:
    return cursor["content"]["value"]


def _parse_timeline(
    data: dict,
    pinned: bool
) -> tuple[list[TimelineEntry], str, str]:
    instructions = data["data"]["user"]["result"]["timeline_v2"]["timeline"]["instructions"]

    entries = []
    cursors = None

    for instruction in instructions:
        if instruction["type"] == "TimelineAddEntries":
            items = instruction["entries"]
            cursors = items[-2:]
            parse = lambda x: (
                _parse_timeline_tweet_entry(x, TimelineEntryType.STATUS_TWEET)
            )

            parsed = list(map(parse, items[:-2]))
            entries.extend(parsed)
        if instruction["type"] == "TimelinePinEntry" and pinned:
            item = instruction["entry"]
            parsed = _parse_timeline_tweet_entry(
                item,
                TimelineEntryType.PINNED_TWEET
            )

            entries.append(parsed)

    cursor_top = _parse_tweet_cursor(cursors[0])
    cursor_bottom = _parse_tweet_cursor(cursors[1])

    return entries, cursor_top, cursor_bottom


class TwitterSession(aiohttp.ClientSession):
    async def __aenter__(self):
        await self.open()

        return await super().__aenter__()

    async def open(self):
        index_source = None
        app_source = None

        async with self.get(TwitterWebapp.URL) as response:
            _validate_status(response)
            index_source = await response.text()

        app_url, guest_token = _parse_app_data(index_source)

        async with self.get(app_url) as response:
            _validate_status(response)
            app_source = await response.text()

        auth_token = _parse_auth_token(app_source)
        self.headers.update(_build_headers(auth_token, guest_token))

    async def get_user_by_handle(self, handle: str) -> TwitterUser:
        url, params = TwitterGraphQl.user_by_handle(handle)

        return _parse_user(await _get_json(self, url, params=params))

    async def get_timeline(
        self,
        user_id: str,
        count: Optional[int] = None,
        cursor: Optional[str] = None,
        pinned: bool = True
    ) -> tuple[list[TimelineEntry], str, str]:
        url, params = TwitterGraphQl.timeline(user_id, count, cursor)

        return _parse_timeline(
            await _get_json(self, url, params=params),
            pinned
        )
