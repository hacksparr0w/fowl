import asyncio

import fowl


async def main():
    async with fowl.ClientSession() as session:
        user = await session.get_user_by_handle("hacksparr0w")
        cursor = None

        while True:
            entries, _, cursor = await session.get_timeline(
                user.rest_id,
                cursor=cursor,
                count=100,
                pinned=cursor is None
            )

            if len(entries) == 0:
                break

            for entry in entries:
                print(entry.tweet)


if __name__ == "__main__":
    asyncio.run(main())
