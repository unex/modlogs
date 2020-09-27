from datetime import datetime, timedelta
from aiohttp import ClientSession, BasicAuth
from aiohttp import client
from pydantic import BaseModel

from models import Guild

# might need this later.....

class ClientCredentials(BaseModel):
    access_token: str
    token_type: str
    expires_in: int
    scope: str
    at = datetime.utcnow()

    @property
    def expired(self):
        return self.at + timedelta(seconds=self.expires_in) < datetime.utcnow()


class Discord(ClientSession):
    API_ENDPOINT = 'https://discord.com/api/v6'

    def __init__(self, token, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

        self.token = token

    async def _request(self, *args, **kwargs):
        args = list(args)
        args[1] = f'{self.API_ENDPOINT}{args[1]}'

        kwargs['headers'] = {
            "Authorization": f'Bot {self.token}',
            "User-Agent": "ModLogs (derw.xyz, 0.0.1)"
        }

        return await super()._request(*args, **kwargs)

    async def guild(self, guild_id):
        async with self.get(f'/guilds/{guild_id}') as r:
            obj = await r.json()
            return Guild.parse_obj(obj)
