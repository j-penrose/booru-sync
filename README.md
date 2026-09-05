# booru-sync
Pull tags, aliases and implications from Danbooru and add them to a [Blombooru](https://github.com/mrblomblo/blombooru) instance.

## Usage
```bash
uv sync
uv run main.py --danbooru-user-id 1234 --blombooru-api-key ADMIN_API_KEY --blombooru-base-url http://localhost:8000
```

All run parameters:
```bash
uv run main.py -h
usage: main.py [-h] --danbooru-user-id DANBOORU_USER_ID --blombooru-api-key BLOMBOORU_API_KEY --blombooru-base-url BLOMBOORU_BASE_URL [--min-post-count MIN_POST_COUNT] [--log-level {DEBUG,INFO,WARNING,ERROR}]

options:
  -h, --help            show this help message and exit
  --danbooru-user-id DANBOORU_USER_ID
                        Your Danbooru user id (can be found under your profile page)
  --blombooru-api-key BLOMBOORU_API_KEY
                        Blombooru API key, must have admin access
  --blombooru-base-url BLOMBOORU_BASE_URL
                        The base url of your Blombooru instance e.g. http://my.blombooru.instance:1234
  --min-post-count MIN_POST_COUNT
                        A tag on Danbooru must have been used on at least this many posts to be synced
  --log-level {DEBUG,INFO,WARNING,ERROR}
```

## License
MIT license. See [LICENSE](LICENSE) for details.