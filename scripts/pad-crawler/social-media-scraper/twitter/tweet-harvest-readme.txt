Powershell> npx tweet-harvest --help
Tweet Harvest [v2.7.1]

Research by Helmi Satria
Use it for Educational Purposes only!

This script uses Chromium Browser to crawl data from Twitter with your Twitter auth token.
Please enter your Twitter auth token when prompted.

Note: Keep your access token secret! Don't share it with anyone else.
Note: This script only runs on your local device.

Usage: npx tweet-harvest [options]

Options:
  -V, --version                 output the version number
  -t, --token <type>            Twitter auth token
  -f, --from <type>             From date (DD-MM-YYYY)
  --to <type>                   To date (DD-MM-YYYY)
  -s, --search-keyword <type>   Search keyword
  --thread <type>               Tweet thread URL
  -l, --limit <number>          Limit number of tweets to crawl
  -d, --delay <number>          Delay between each tweet (in seconds) (default: 3)
  -o, --output-filename <type>  Output filename
  --tab <type>                  Search tab (choices: "TOP", "LATEST", default: "TOP")
  -e, --export-format <type>    Export format (choices: "csv", "xlsx", default: "csv")
  -h, --help                    display help for command


Link: https://x.com/elonmusk/status/1675187969420828672
Content:
To address extreme levels of data scraping & system manipulation, we've applied the following temporary limits:

- Verified accounts are limited to reading 6000 posts/day
- Unverified accounts to 600 posts/day
- New unverified accounts to 300/day

JSON Documentation
"conversation_id_str": ID percakapan (thread) tempat tweet tersebut berada,
"created_at": tanggal_tweet,
"favorite_count": jumlah_likes,
"full_text": text_content,
"id_str": ID unik tweet,
"image_url": thumbnail_img_link,
"in_reply_to_screen_name": Username yang dibalas oleh tweet ini,
"lang": Bahasa tweet yang terdeteksi otomatis oleh sistem,
"location": Lokasi user (jika user mengisi profil lokasi),
"quote_count": Jumlah quote tweet. Quote tweet = tweet yang mengutip tweet ini,
"reply_count": jumlah_reply,
"retweet_count": jumlah_retweet,
"tweet_url": Link langsung ke tweet,
"user_id_str": ID unik pengguna,
"username": Username akun yang membuat tweet