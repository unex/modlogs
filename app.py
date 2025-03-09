import os
import traceback
from secrets import token_urlsafe
from urllib.parse import urljoin
from contextlib import asynccontextmanager

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

from models import LogEntry, Config, Guild, CacheGuild, GuildMember, DiscordUser, User

CONNECTION_URI = os.environ.get("CONNECTION_URI")

DISCORD_CLIENT_ID = os.environ.get("DISCORD_CLIENT_ID")
DISCORD_CLIENT_SECRET = os.environ.get("DISCORD_CLIENT_SECRET")

LOG_URL = os.environ.get("LOG_URL")
SECRET_KEY = os.environ.get("SECRET_KEY", "this_should_be_configured")
SERIALIZER = URLSafeSerializer(SECRET_KEY)


mongo = AsyncIOMotorClient(CONNECTION_URI)
db = mongo.modmail_bot
logs: Collection = db.logs
users: Collection = db.users
config: Collection = db.config
cache: Collection = db.plugins.Cache


@asynccontextmanager
async def lifespan(app: FastAPI):
    await mongo.admin.command("ismaster")

    yield

    mongo.close()


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)


def make_discord_session(access_token=None) -> DiscordClient:
    return DiscordClient(
        DISCORD_CLIENT_ID, DISCORD_CLIENT_SECRET, access_token=access_token
    )


class RequiresAuth(HTTPException):
    pass


async def auth(request: Request):
    if "goto" in request.session:
        del request.session["goto"]
    if "user" in request.session:
        if user := await db.users.find_one(
            {"_id": ObjectId(SERIALIZER.loads(request.session["user"]))}
        ):
            return User.model_validate(user)

    raise RequiresAuth(status_code=status.HTTP_401_UNAUTHORIZED)


@app.exception_handler(RequiresAuth)
async def no_user_exception_handler(request: Request, exc: Exception):
    request.session["goto"] = SERIALIZER.dumps(request.url.path)
    return RedirectResponse(request.url_for("login"))


@app.get("/")
async def root(request: Request, user=Depends(auth)):
    cached = { doc["id"] : CacheGuild(**doc) async for doc in cache.find({"id": {"$in": list(map(int, user.guilds))}}) }
    doc = (
        await logs.find({"guild_id": {"$in": list(map(str, user.guilds))}})
        .sort([("created_at", -1)])
        .to_list(100)
    )
    entries = [LogEntry(**{**x, "guild": cached[int(x["guild_id"])]}) for x in doc]
    return templates.TemplateResponse(
        "home.html", {"request": request, "user": user, "entries": entries}
    )


async def get_authorized_guilds(discord):
    guilds = [ Guild.model_validate(obj) for obj in await discord.request("GET", "users/@me/guilds") ]
    cached = { doc["id"] : CacheGuild(**doc) async for doc in cache.find({"id": {"$in": [g.id for g in guilds]}}) }

    if not cached:
        return

    member_data = [ await discord.request("GET", f"users/@me/guilds/{g_id}/member") for g_id in cached ]
    member = [ GuildMember.model_validate(m) for m in member_data if not m.get("message") ]
    configs = [ Config(**doc) async for doc in config.find() ]

    if not member:
        return

    user = member[0].user

    user_check = set()
    for m in member:
        user_check.update(m.roles)

    user_check.add(user.id)

    allowed_bots = set()

    for g in guilds:
        if g.id not in cached.keys():
            continue

        for c in configs:
            if not c.bot_id in cached[g.id].bot_ids:
                continue

            if user_check & set(c.oauth_whitelist) \
                    or user_check & set(map(int, c.level_permissions.get("OWNER", []))) \
                    or user_check & set(map(int, c.level_permissions.get("MODERATOR", []))) \
                    or g.permissions & 32: # manage guild

                allowed_bots.add(c.bot_id)

    allowed_guilds = set()

    for _,g in cached.items():
        if allowed_bots & set(g.bot_ids):
            allowed_guilds.add(g.id)

    doc = await users.find_one_and_update(
        {"id": user.id},
        {"$set": {**user.model_dump(), **{"guilds": list(allowed_guilds)}}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )

    return doc


@app.get("/login")
async def login(
    request: Request, code: str = None, state: str = None, error: str = None
):
    if not code:
        state = token_urlsafe()
        auth_url = make_discord_session().get_authorize_url(
            scope="identify guilds guilds.members.read",
            redirect_uri=urljoin(LOG_URL, request.url.path),
            state=state,
        )
        request.session["oauth2_state"] = state
        return RedirectResponse(auth_url)

    if error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"There was an error authenticating with discord: {error}",
        )

    # Verify state
    if request.session.get("oauth2_state") != state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"State mismatch"
        )

    # Fetch token
    discord = make_discord_session()

    try:
        await discord.get_access_token(
            code, redirect_uri=urljoin(LOG_URL, request.url.path)
        )

    except Exception as e:
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"There was an error authenticating with discord: {e}",
        )

    doc = await get_authorized_guilds(discord)

    if not doc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"You do not have access to modlogs in any guilds",
        )

    request.session["user"] = SERIALIZER.dumps(str(doc.get("_id")))

    if goto := request.session.get("goto"):
        target = SERIALIZER.loads(goto)
    else:
        target = app.url_path_for("root")

    return RedirectResponse(target)


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return templates.TemplateResponse(
        "page.html", {"request": request, "content": "goodbye"}
    )


@app.get("/logs/{key}")
async def log_page(request: Request, key: str, user=Depends(auth)):
    cached = { doc["id"] : CacheGuild(**doc) async for doc in cache.find({"id": {"$in": list(map(int, user.guilds))}}) }
    doc = await logs.find_one({"key": key})
    entry = LogEntry(**{**doc, "guild": cached[int(doc["guild_id"])]})

    if entry.guild_id not in user.guilds:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"You do not have access to modlogs for this guild",
        )

    return templates.TemplateResponse(
        "log.html", {"request": request, "user": user, "entry": entry}
    )
