import os
import traceback
from secrets import token_urlsafe
from urllib.parse import urljoin

from fastapi import FastAPI, Request, Depends, HTTPException, status
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse

from starlette.middleware.sessions import SessionMiddleware
from itsdangerous.url_safe import URLSafeSerializer

from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.collection import Collection
from pymongo import ReturnDocument
from bson.objectid import ObjectId

from aioauth_client import DiscordClient

from models import LogEntry, Guild, DiscordUser, User
# from discord import Discord

CONNECTION_URI = os.environ.get("CONNECTION_URI")

DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")
DISCORD_CLIENT_ID = os.environ.get("DISCORD_CLIENT_ID")
DISCORD_CLIENT_SECRET = os.environ.get("DISCORD_CLIENT_SECRET")

LOG_URL = os.environ.get("LOG_URL")
SECRET_KEY = os.environ.get('SECRET_KEY', 'this_should_be_configured')
SERIALIZER = URLSafeSerializer(SECRET_KEY)

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)


mongo = AsyncIOMotorClient(CONNECTION_URI)
db = mongo.modmail_bot
logs: Collection = db.logs
users: Collection = db.users

# discord = Discord(DISCORD_TOKEN)


def make_discord_session(access_token=None) -> DiscordClient:
    return DiscordClient(
        DISCORD_CLIENT_ID,
        DISCORD_CLIENT_SECRET,
        access_token=access_token
    )

class RequiresAuth(HTTPException):
    pass

async def auth(request: Request):
    if 'goto' in request.session:
        del request.session['goto']
    if 'user' in request.session:
        if (user := await db.users.find_one({"_id": ObjectId(SERIALIZER.loads(request.session['user']))})):
            return User.parse_obj(user)

    raise RequiresAuth(status_code=status.HTTP_401_UNAUTHORIZED)


@app.exception_handler(RequiresAuth)
async def no_user_exception_handler(request: Request, exc: Exception):
    request.session["goto"] = SERIALIZER.dumps(request.url.path)
    return RedirectResponse(request.url_for('login'))


@app.on_event("startup")
async def create_db_client():
    await mongo.admin.command("ismaster")

@app.on_event("shutdown")
async def shutdown_db_client():
    await mongo.close()

@app.get('/')
async def root(request: Request, user = Depends(auth)):
    doc = await logs.find({'guild_id': {'$in': list(map(str, user.guilds))}}).sort([('created_at', -1)]).to_list(100)
    entries = [LogEntry.parse_obj(x) for x in doc]
    return templates.TemplateResponse('home.html', {'request': request, 'user': user, 'entries': entries})

@app.get('/login')
async def login(request: Request, code: str = None, state: str = None, error: str = None):
    if not code:
        state = token_urlsafe()
        auth_url = make_discord_session().get_authorize_url(scope='identify guilds', redirect_uri=urljoin(LOG_URL, request.url.path), state=state)
        request.session['oauth2_state'] = state
        return RedirectResponse(auth_url)

    if error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f'There was an error authenticating with discord: {error}'
        )

    #Verify state
    if request.session.get('oauth2_state') != state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f'State mismatch'
        )

    # Fetch token
    discord = make_discord_session()

    try:
        await discord.get_access_token(code, redirect_uri=urljoin(LOG_URL, request.url.path))

    except Exception as e:
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f'There was an error authenticating with discord: {e}'
        )

    user = DiscordUser.parse_obj(await discord.request('GET', 'users/@me'))
    guilds = [Guild.parse_obj(obj) for obj in await discord.request('GET', 'users/@me/guilds') if int(obj.get('permissions')) & 32]

    log_guilds = list(map(int, await logs.distinct('guild_id')))

    if not any(x.id in log_guilds for x in guilds):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f'You do not have access to modlogs in any guilds'
        )

    doc = await users.find_one_and_update(
        {'id': user.id},
        {"$set": {
            **user.dict(),
            **{"guilds": [guild.id for guild in guilds]}
        }},
        upsert=True,
        return_document=ReturnDocument.AFTER
    )

    request.session["user"] = SERIALIZER.dumps(str(doc.get('_id')))

    target = SERIALIZER.loads(request.session.get('goto')) or app.url_path_for('root')
    return RedirectResponse(target)

@app.get('/logout')
async def logout(request: Request):
    request.session.clear()
    return 'goodbye'

@app.get('/logs/{key}')
async def log_page(request: Request, key: str, user = Depends(auth)):
    doc = await logs.find_one({'key': key})
    entry = LogEntry.parse_obj(doc)

    if entry.guild_id not in user.guilds:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f'You do not have access to modlogs for this guild'
        )

    return templates.TemplateResponse('log.html', {'request': request, 'user': user, 'entry': entry})
