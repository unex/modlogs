from typing import List, Optional
from datetime import datetime

from pydantic import BaseModel
from discord_markdown.discord_markdown import convert_to_html


class LogEntry(BaseModel):
    _id: str
    key: str
    open: bool
    created_at: datetime
    closed_at: Optional[datetime] = None
    channel_id: int
    guild_id: int
    bot_id: int
    recipient: "LogUser"
    creator: "LogUser"
    closer: Optional["LogUser"] = None
    messages: List["Message"] = []
    close_message: Optional[str]

    @property
    def closed(self):
        return self.closed_at is not None

    @property
    def close_message_html(self) -> str:
        return convert_to_html(self.close_message)


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


class Message(BaseModel):
    timestamp: datetime
    message_id: int
    author: "LogUser"
    content: str
    type: str
    attachments: List["Attachment"] = []

    @property
    def content_html(self) -> str:
        return convert_to_html(self.content)


class Attachment(BaseModel):
    id: int
    filename: str
    is_image: bool
    size: int
    url: str


LogEntry.update_forward_refs()
Message.update_forward_refs()


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


class Guild(BaseModel):
    id: int
    name: str
    icon: Optional[str] = ""
    description: Optional[str] = ""


# DB


class User(DiscordUser):
    guilds: List[int]

    @property
    def avatar_url(self):
        return f"https://cdn.discordapp.com/avatars/{self.id}/{self.avatar}.png"
