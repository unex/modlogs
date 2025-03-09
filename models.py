from typing import Any, List, Dict, Optional
from datetime import datetime

from pydantic import BaseModel
from discord_markdown.discord_markdown import convert_to_html


class LogUser(BaseModel):
    id: int
    name: str
    discriminator: str
    avatar_url: str
    mod: bool

    @property
    def fullname(self) -> str:
        if self.discriminator == '0':
            return self.name

        return f"{self.name}#{self.discriminator}"


class LogEntry(BaseModel):
    _id: str
    key: str
    open: bool
    created_at: datetime
    closed_at: Optional[datetime] = None
    channel_id: int
    guild_id: int
    bot_id: int
    recipient: LogUser
    creator: LogUser
    closer: Optional[LogUser] = None
    messages: List["Message"] = []
    close_message: Optional[str] = ""

    guild: Optional["CacheGuild"] = None

    @property
    def closed(self):
        return self.closed_at is not None

    @property
    def close_message_html(self) -> str:
        return convert_to_html(self.close_message)


class Attachment(BaseModel):
    id: int
    filename: str
    is_image: bool
    size: int
    url: str


class Message(BaseModel):
    timestamp: datetime
    message_id: int
    author: LogUser
    content: str
    type: str
    attachments: List[Attachment] = []

    @property
    def content_html(self) -> str:
        return convert_to_html(self.content)


# Discord


class DiscordUser(BaseModel):
    id: int
    username: str
    avatar: str
    discriminator: str
    global_name: str

    @property
    def fullname(self) -> str:
        if self.discriminator == '0':
            return self.username

        return f"{self.username}#{self.discriminator}"


class GuildMember(BaseModel):
    user: DiscordUser
    roles: List[int]


class Guild(BaseModel):
    id: int
    name: str
    icon: Optional[str] = ""
    description: Optional[str] = ""
    permissions: int


# DB


class User(DiscordUser):
    guilds: List[int]

    @property
    def avatar_url(self):
        return f"https://cdn.discordapp.com/avatars/{self.id}/{self.avatar}.png"


class Config(BaseModel):
    bot_id: int
    main_category_id: Optional[int] = None
    oauth_whitelist: Optional[List[int]] = []
    level_permissions: Optional[Dict[str, List[Any]]] = []


class CacheGuild(BaseModel):
    id: int
    name: str
    icon: str
    channels: List[int]
    roles: List[int]
    bot_ids: List[int]

    @property
    def icon_url(self):
        return f"https://cdn.discordapp.com/icons/{self.id}/{self.icon}.jpg"


LogEntry.model_rebuild()
Message.model_rebuild()
