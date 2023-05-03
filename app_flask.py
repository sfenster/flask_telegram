import os
import dotenv
import asyncio
import sqlite3
from flask import Flask, render_template, jsonify
from telethon import TelegramClient, events

dotenv.load_dotenv()
api_id = os.environ.get('API_ID')
api_hash = os.environ.get('API_HASH')
session_name = 'flask_api_session'



app = Flask(__name__)
client = TelegramClient(session=session_name, api_id=api_id, api_hash=api_hash)

async def start_telegram_client():
    global client
    await client.start()
    # await client.run_until_disconnected()


async def get_channels():
    global client
    channels = ""
    async for dialog in client.iter_dialogs():
        channels += 'Chat ID: ' + \
            str(dialog.id) + ' Chat Title: ' + dialog.title + "\n"
    return jsonify({"channels": channels})


#@app.teardown_request
#async def teardown_request(exception=None):
#    await client.disconnect()


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/channels', methods=['GET'])
async def channels():
    # r = client.loop.run_until_complete(get_channels())
    r = await get_channels()
    return r

#asyncio.get_event_loop().run_until_complete(start_telegram_client())
# client.loop.run_until_complete(start_telegram_client())
asyncio.run(start_telegram_client())
if __name__ == '__main__':
    app.run(debug=True)
