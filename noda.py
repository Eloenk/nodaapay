import asyncio
import aiohttp
import json
import time
import uuid
from loguru import logger

# Constants
NP_TOKEN = "WRITE_YOUR_NP_TOKEN_HERE"
PING_INTERVAL = 30  # seconds
RETRIES = 60  # Global retry counter for ping failures

DOMAIN_API = {
    "SESSION": "https://api.nodepay.ai/api/auth/session",
    "PING": "https://nw2.nodepay.ai/api/network/ping"
}

CONNECTION_STATES = {
    "CONNECTED": 1,
    "DISCONNECTED": 2,
    "NONE_CONNECTION": 3
}


class ProxyManager:
    def __init__(self, np_token, proxy):
        self.token_info = np_token
        self.proxy = proxy
        self.browser_id = str(uuid.uuid4())
        self.account_info = {}
        self.status_connect = CONNECTION_STATES["NONE_CONNECTION"]
        self.retries = 0

    async def call_api(self, url, data):
        """Make an API call using the given proxy"""
        headers = {
            "Authorization": f"Bearer {self.token_info}",
            "Content-Type": "application/json"
        }
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(url, json=data, headers=headers, proxy=self.proxy, timeout=10) as resp:
                    response = await resp.json()
                    return self.valid_resp(response)
            except aiohttp.ClientError as e:
                logger.error(f"Error during API call: {e}")
                raise ValueError(f"Failed API call to {url}")

    @staticmethod
    def valid_resp(resp):
        """Validate API response"""
        if not resp or "code" not in resp or resp["code"] < 0:
            raise ValueError("Invalid response")
        return resp

    async def start_ping(self):
        """Continuously ping the server to keep the session alive"""
        try:
            await self.ping()
            while True:
                await asyncio.sleep(PING_INTERVAL)
                await self.ping()
        except asyncio.CancelledError:
            logger.info(f"Ping task for proxy {self.proxy} was cancelled")
        except Exception as e:
            logger.error(f"Error in start_ping for proxy {self.proxy}: {e}")

    async def ping(self):
        """Send a ping request to the server"""
        data = {
            "id": self.account_info.get("uid"),
            "browser_id": self.browser_id,
            "timestamp": int(time.time())
        }

        try:
            response = await self.call_api(DOMAIN_API["PING"], data)
            if response["code"] == 0:
                logger.info(f"Ping successful via proxy {self.proxy}: {response}")
                self.retries = 0
                self.status_connect = CONNECTION_STATES["CONNECTED"]
            else:
                self.handle_ping_fail(response)
        except Exception as e:
            logger.error(f"Ping failed via proxy {self.proxy}: {e}")
            self.handle_ping_fail(None)

    def handle_ping_fail(self, response):
        """Handle failed ping attempts"""
        self.retries += 1
        if response and response.get("code") == 403:
            self.handle_logout()
        elif self.retries < RETRIES:
            self.status_connect = CONNECTION_STATES["DISCONNECTED"]
        else:
            self.status_connect = CONNECTION_STATES["DISCONNECTED"]

    def handle_logout(self):
        """Log out and reset session info"""
        self.token_info = None
        self.status_connect = CONNECTION_STATES["NONE_CONNECTION"]
        self.account_info = {}
        logger.info(f"Logged out and cleared session info for proxy {self.proxy}")

    async def render_profile_info(self):
        """Load session info or authenticate with the API to get session"""
        try:
            np_session_info = self.load_session_info()

            if not np_session_info:
                response = await self.call_api(DOMAIN_API["SESSION"], {})
                self.account_info = response["data"]
                if self.account_info.get("uid"):
                    self.save_session_info(self.account_info)
                    await self.start_ping()
                else:
                    self.handle_logout()
            else:
                self.account_info = np_session_info
                await self.start_ping()
        except Exception as e:
            logger.error(f"Error in render_profile_info for proxy {self.proxy}: {e}")
            return None

    def load_session_info(self):
        """Load session info (placeholder for actual implementation)"""
        return {}

    def save_session_info(self, data):
        """Save session info (placeholder for actual implementation)"""
        pass


async def fetch_proxies(url):
    """Fetch proxies from a remote URL"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    return await resp.text()
                else:
                    logger.error(f"Failed to fetch proxies: {resp.status}")
                    raise ValueError("Failed to fetch proxies")
    except aiohttp.ClientError as e:
        logger.error(f"Error fetching proxies: {e}")
        raise ValueError("Failed to fetch proxies")


async def main():
    """Main function to load and process proxies"""
    # Fetch proxies from a remote URL
    proxy_url = "https://github.com/monosans/proxy-list/raw/main/proxies/http.txt"
    proxies_text = await fetch_proxies(proxy_url)
    proxies = proxies_text.splitlines()

    active_proxies = [proxy for proxy in proxies[:100]]  # Limit to 100 at a time

    tasks = {asyncio.create_task(ProxyManager(NP_TOKEN, proxy).render_profile_info()): proxy for proxy in active_proxies}

    while tasks:
        done, _ = await asyncio.wait(tasks.keys(), return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            if task.result() is None:
                failed_proxy = tasks.pop(task)
                logger.info(f"Proxy failed: {failed_proxy}")

        await asyncio.sleep(3)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Program terminated by user.")