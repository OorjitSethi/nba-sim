from __future__ import annotations

import re
import unicodedata


# NBA.com's published NBA 2K26 launch ratings provide a scale anchor, not a
# final answer. Current official performance and the lifecycle model update
# these priors for the 2026-27 franchise season.
_PUBLISHED_2K26_RATINGS = {
    "Nikola Jokic": 98,
    "Shai Gilgeous-Alexander": 98,
    "Giannis Antetokounmpo": 97,
    "Luka Doncic": 95,
    "Anthony Edwards": 95,
    "Stephen Curry": 94,
    "LeBron James": 94,
    "Jayson Tatum": 94,
    "Victor Wembanyama": 94,
    "Kevin Durant": 93,
    "Donovan Mitchell": 93,
    "Anthony Davis": 93,
    "Jalen Brunson": 93,
    "Tyrese Haliburton": 93,
    "Kawhi Leonard": 92,
    "Cade Cunningham": 92,
    "Joel Embiid": 92,
    "Karl-Anthony Towns": 92,
    "Ja Morant": 91,
    "Devin Booker": 91,
    "Jalen Williams": 90,
    "Jaylen Brown": 90,
    "Trae Young": 90,
    "Kyrie Irving": 90,
    "Paolo Banchero": 89,
    "Evan Mobley": 89,
    "Pascal Siakam": 89,
    "James Harden": 89,
    "Jaren Jackson Jr.": 89,
    "Bam Adebayo": 88,
    "Chet Holmgren": 88,
    "Damian Lillard": 88,
    "Domantas Sabonis": 87,
    "Alperen Sengun": 87,
    "LaMelo Ball": 87,
    "Darius Garland": 87,
    "Zion Williamson": 87,
    "Ivica Zubac": 87,
    "Derrick White": 87,
    "Jimmy Butler": 87,
    "Amen Thompson": 87,
    "Tyler Herro": 86,
    "Tyrese Maxey": 86,
    "Jamal Murray": 86,
    "Franz Wagner": 86,
    "Julius Randle": 86,
    "Zach LaVine": 85,
    "De'Aaron Fox": 85,
    "Austin Reaves": 85,
    "DeMar DeRozan": 85,
    "Scottie Barnes": 85,
    "OG Anunoby": 85,
    "Kristaps Porzingis": 85,
    "Lauri Markkanen": 84,
    "Brandon Ingram": 84,
    "Mikal Bridges": 84,
    "Rudy Gobert": 84,
    "Norman Powell": 84,
    "Jarrett Allen": 83,
    "Desmond Bane": 83,
    "Jalen Green": 83,
    "Myles Turner": 83,
    "Cameron Johnson": 83,
    "Dyson Daniels": 83,
    "Coby White": 83,
    "Stephon Castle": 82,
    "Michael Porter Jr.": 82,
    "RJ Barrett": 82,
    "Josh Giddey": 82,
    "John Collins": 82,
    "Aaron Gordon": 82,
    "Brandon Miller": 82,
    "Deni Avdija": 82,
    "Naz Reid": 82,
    "Nikola Vucevic": 82,
    "Jalen Duren": 82,
    "Jalen Suggs": 82,
    "Trey Murphy III": 82,
    "Cooper Flagg": 82,
    "Isaiah Hartenstein": 82,
    "Jaden McDaniels": 82,
    "Toumani Camara": 82,
    "Walker Kessler": 82,
    "Luguentz Dort": 81,
    "Herbert Jones": 81,
    "Jrue Holiday": 81,
    "Dejounte Murray": 81,
    "CJ McCollum": 81,
    "Anfernee Simons": 81,
    "Draymond Green": 81,
    "Josh Hart": 81,
    "Paul George": 81,
    "Onyeka Okongwu": 81,
    "Immanuel Quickley": 81,
    "Andrew Nembhard": 81,
    "Jalen Johnson": 81,
    "Alex Sarr": 81,
    "Aaron Nesmith": 81,
    "Shaedon Sharpe": 81,
    "Bobby Portis": 81,
}


def published_2k26_rating(player_name: str) -> int | None:
    normalized = normalize_player_name(player_name)
    rating = _NORMALIZED_RATINGS.get(normalized)
    if rating is None:
        return None
    # The franchise scale reserves 99 for the best possible active player.
    return 99 if rating == 98 else rating


def normalize_player_name(player_name: str) -> str:
    value = unicodedata.normalize("NFKD", player_name)
    value = "".join(character for character in value if not unicodedata.combining(character))
    value = value.replace("’", "'").replace("‘", "'").replace(".", "")
    value = re.sub(r"\b(?:Jr|Sr|II|III|IV)\b$", "", value, flags=re.IGNORECASE)
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


_NORMALIZED_RATINGS = {
    normalize_player_name(name): rating
    for name, rating in _PUBLISHED_2K26_RATINGS.items()
}


__all__ = ["published_2k26_rating", "normalize_player_name"]
