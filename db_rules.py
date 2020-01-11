""" Sets the database access rules for the firestore database for the print client"""
import json
import logging

from google import auth
from google.auth.transport.requests import AuthorizedSession

# set the rules here according to the firestore format
DB_RULES = {
    "rules": {
        "print_queue": {
            ".read":  "auth !== null",
            ".write": "auth !== null",
            ".indexOn": ["order_number"]
        }
    }
}


def main():
    """ Sets the database access rules for the firestore database for the print client"""
    # Define the required scopes
    scopes = [
        "https://www.googleapis.com/auth/userinfo.email",
        "https://www.googleapis.com/auth/firebase.database"
    ]

    # Authenticate a credential with the service account
    credentials, project = auth.default(scopes=scopes)

    # Use the credentials object to authenticate a Requests session.
    authed_session = AuthorizedSession(credentials)
    url = "https://%s.firebaseio.com/.settings/rules.json" % project

    logging.debug("sending updated rules to '%s': %s", url, json.dumps(DB_RULES))
    response = authed_session.put(url, json=DB_RULES)

    if response.status_code != 200:
        logging.error("error updating rules:(%s) %s", response.status_code, response.text)
    else:
        logging.info("rules successfully updated")


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    main()
