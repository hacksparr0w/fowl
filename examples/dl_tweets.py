import asyncio
import os
import sys

import aiohttp
import fowl
import yaml


def get_tweet_content(tweet: dict) -> str:
    result = tweet["content"]["itemContent"]["tweet_results"]["result"]
    text = result["legacy"]["full_text"]

    return text


def format_tweet(tweet: dict, first: bool = True) -> str:
    data = None

    result = tweet["content"]["itemContent"]["tweet_results"]["result"]
    type = result["__typename"]

    if type == "TweetTombstone":
        data = {
            "type": type,
            "text": result["tombstone"]["text"]["text"]
        }
    elif type == "Tweet":
        legacy = result["legacy"]
        data = {
            "type": type,
            "text": legacy["full_text"],
            "likes": legacy["favorite_count"],
            "retweets": legacy["retweet_count"],
            "bookmarks": legacy["bookmark_count"],
            "created_at": legacy["created_at"]
        }
    else:
        raise ValueError

    formatted = ""

    if not first:
        formatted += "---"
        formatted += "\n"

    formatted += yaml.dump(data, allow_unicode=True, sort_keys=True)
    formatted += "\n"

    return formatted


async def main():
    args = sys.argv[1:]

    if len(args) != 1:
        print("Usage: python dl_tweets.py <username>")
        sys.exit(1)

    username = sys.argv[1]

    async with fowl.TwitterSession() as session:
        user = await session.get_user_by_username(username)
        user_id = user["rest_id"]

        with open("tweets.yaml", "w", encoding="utf-8") as stream:
            cursor = None

            while True:
                tweets, _, cursor = await session.get_tweets(
                    user_id,
                    cursor=cursor,
                    count=100
                )

                if len(tweets) == 0:
                    break

                for index, tweet in enumerate(tweets):
                    if index == len(tweets) - 2:
                        break

                    first = index == 0
                    formatted = format_tweet(tweet, first)
                    stream.write(formatted)


if __name__ == "__main__":
    if os.name == 'nt':
        asyncio.set_event_loop_policy(
            asyncio.WindowsSelectorEventLoopPolicy()
        )

    asyncio.run(main())
