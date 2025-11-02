import os
import json
import time
import sys
import requests

class Auth:
    _instance_ = None
    _initialized_ = False

    api_key = ""

    refresh_tokens = []
    active_user = None
    last_refresh_time = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance_:
            cls._instance_ = super().__new__(cls)
        return cls._instance_

    def __init__(self):
        if not self._initialized_:
            self.prompt_for_api_key()

            if os.path.exists("refresh-tokens.json"):
                self.load_tokens()
            else:
                # Create empty file
                with open("refresh-tokens.json", "w", encoding="utf-8") as f:
                    json.dump([], f, indent=4)

            # Select active user from file if available
            self.load_active_number()
            self.last_refresh_time = int(time.time())

            self._initialized_ = True

    def prompt_for_api_key(self):
        """Prompt user for API key and verify it"""
        # Try to load from existing file first
        if os.path.exists("api.key"):
            with open("api.key", "r", encoding="utf-8") as f:
                existing_key = f.read().strip()
                if existing_key and self.verify_api_key(existing_key):
                    self.api_key = existing_key
                    print("API key loaded successfully.")
                    return

        # Prompt for new key
        print("Dapatkan API key di Bot Telegram @fyxt_bot")
        api_key = input("Masukkan API key: ").strip()
        if not api_key:
            print("API key tidak boleh kosong. Menutup aplikasi.")
            sys.exit(1)

        if not self.verify_api_key(api_key):
            print("API key tidak valid. Menutup aplikasi.")
            if os.path.exists("api.key"):
                os.remove("api.key")
            sys.exit(1)

        # Save the valid key
        with open("api.key", "w", encoding="utf-8") as f:
            f.write(api_key)
        print("API key saved successfully.")
        self.api_key = api_key

    def verify_api_key(self, api_key: str, timeout: float = 10.0) -> bool:
        """
        Returns True iff the verification endpoint responds with HTTP 200.
        Any network error or non-200 is treated as invalid.
        """
        try:
            url = f"https://crypto.mashu.lol/api/verify?key={api_key}"
            resp = requests.get(url, timeout=timeout)
            if resp.status_code == 200:
                json_resp = resp.json()
                print(
                    f"API key is valid.\n"
                    f"Id: {json_resp.get('user_id')}\n"
                    f"Owner: @{json_resp.get('username')}\n"
                    f"Credit: {json_resp.get('credit')}\n"
                    f"Premium Credit: {json_resp.get('premium_credit')}\n"
                )
                return True
            else:
                print(f"API key is invalid. Server responded with status code {resp.status_code}.")
                return False
        except requests.RequestException as e:
            print(f"Failed to verify API key: {e}")
            return False

    def load_tokens(self):
        with open("refresh-tokens.json", "r", encoding="utf-8") as f:
            refresh_tokens = json.load(f)

            if len(refresh_tokens) !=  0:
                self.refresh_tokens = []

            # Validate and load tokens
            for rt in refresh_tokens:
                if "number" in rt and "refresh_token" in rt:
                    self.refresh_tokens.append(rt)
                else:
                    print(f"Invalid token entry: {rt}")

    def add_refresh_token(self, number: int, refresh_token: str):
        # Use local import to avoid circular dependency
        from app.client.engsel import get_new_token, get_profile
        
        # Check if number already exist, if yes, replace it, if not append
        existing = next((rt for rt in self.refresh_tokens if rt["number"] == number), None)
        if existing:
            existing["refresh_token"] = refresh_token
        else:
            tokens = get_new_token(refresh_token)
            profile_data = get_profile(self.api_key, tokens["access_token"], tokens["id_token"])
            sub_id = profile_data["profile"]["subscriber_id"]
            sub_type = profile_data["profile"]["subscription_type"]

            self.refresh_tokens.append({
                "number": int(number),
                "subscriber_id": sub_id,
                "subscription_type": sub_type,
                "refresh_token": refresh_token
            })

        # Save to file
        self.write_tokens_to_file()

        # Set active user to newly added
        self.set_active_user(number)

    def remove_refresh_token(self, number: int):
        self.refresh_tokens = [rt for rt in self.refresh_tokens if rt["number"] != number]

        # Save to file
        with open("refresh-tokens.json", "w", encoding="utf-8") as f:
            json.dump(self.refresh_tokens, f, indent=4)

        # If the removed user was the active user, select a new active user if available
        if self.active_user and self.active_user["number"] == number:
            # Use local import to avoid circular dependency
            from app.client.engsel import get_new_token
            
            # Select the first user as active user by default
            if len(self.refresh_tokens) != 0:
                first_rt = self.refresh_tokens[0]
                tokens = get_new_token(first_rt["refresh_token"])
                if tokens:
                    self.set_active_user(first_rt["number"])
            else:
                input("No users left. Press Enter to continue...")
                self.active_user = None

    def set_active_user(self, number: int):
        # Use local import to avoid circular dependency
        from app.client.engsel import get_new_token, get_profile
        
        # Get refresh token for the number from refresh_tokens
        rt_entry = next((rt for rt in self.refresh_tokens if rt["number"] == number), None)
        if not rt_entry:
            print(f"No refresh token found for number: {number}")
            input("Press Enter to continue...")
            return False

        tokens = get_new_token(rt_entry["refresh_token"])
        if not tokens:
            print(f"Failed to get tokens for number: {number}. The refresh token might be invalid or expired.")
            input("Press Enter to continue...")
            return False

        # Get subscriber_id and subscription_type if not already stored
        subscriber_id = rt_entry.get("subscriber_id", "")
        subscription_type = rt_entry.get("subscription_type", "")
        if not subscriber_id or not subscription_type:
            profile_data = get_profile(self.api_key, tokens["access_token"], tokens["id_token"])
            subscriber_id = profile_data["profile"]["subscriber_id"]
            subscription_type = profile_data["profile"]["subscription_type"]

        self.active_user = {
            "number": int(number),
            "subscriber_id": subscriber_id,
            "subscription_type": subscription_type,
            "tokens": tokens
        }

        # Update refresh token entry with subscriber_id and subscription_type
        rt_entry["subscriber_id"] = subscriber_id
        rt_entry["subscription_type"] = subscription_type

        # Update refresh token. The real client app do this, not sure why cz refresh token should still be valid
        rt_entry["refresh_token"] = tokens["refresh_token"]
        self.write_tokens_to_file()

        self.last_refresh_time = int(time.time())

        # Save active number to file
        self.write_active_number()

    def renew_active_user_token(self):
        # Use local import to avoid circular dependency
        from app.client.engsel import get_new_token
        
        if self.active_user:
            tokens = get_new_token(self.active_user["tokens"]["refresh_token"])
            if tokens:
                self.active_user["tokens"] = tokens
                self.last_refresh_time = int(time.time())
                self.add_refresh_token(self.active_user["number"], self.active_user["tokens"]["refresh_token"])

                print("Active user token renewed successfully.")
                return True
            else:
                print("Failed to renew active user token.")
                input("Press Enter to continue...")
        else:
            print("No active user set or missing refresh token.")
            input("Press Enter to continue...")
        return False

    def get_active_user(self):
        # Use local import to avoid circular dependency
        from app.client.engsel import get_new_token
        
        if not self.active_user:
            # Choose the first user if available
            if len(self.refresh_tokens) != 0:
                first_rt = self.refresh_tokens[0]
                tokens = get_new_token(first_rt["refresh_token"])
                if tokens:
                    self.set_active_user(first_rt["number"])
            return None

        if self.last_refresh_time is None or (int(time.time()) - self.last_refresh_time) > 300:
            self.renew_active_user_token()
            self.last_refresh_time = time.time()

        return self.active_user

    def get_active_tokens(self) -> dict | None:
        active_user = self.get_active_user()
        return active_user["tokens"] if active_user else None

    def write_tokens_to_file(self):
        with open("refresh-tokens.json", "w", encoding="utf-8") as f:
            json.dump(self.refresh_tokens, f, indent=4)

    def write_active_number(self):
        if self.active_user:
            with open("active.number", "w", encoding="utf-8") as f:
                f.write(str(self.active_user["number"]))
        else:
            if os.path.exists("active.number"):
                os.remove("active.number")

    def load_active_number(self):
        if os.path.exists("active.number"):
            with open("active.number", "r", encoding="utf-8") as f:
                number_str = f.read().strip()
                if number_str.isdigit():
                    number = int(number_str)
                    self.set_active_user(number)

AuthInstance = Auth()
