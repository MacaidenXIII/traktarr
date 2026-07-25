from misc.log import logger
import requests

log = logger.get_logger(__name__)

# ======================================================
# PASTE YOUR TMDB API KEY BETWEEN THE QUOTES BELOW
# ======================================================
TMDB_API_KEY = 'c9fb29cf75205145143ad7e2a5543723'
# ======================================================

def validate_movie_tmdb_id(movie_title, movie_year, movie_tmdb_id):
    try:
        if not movie_tmdb_id or not isinstance(movie_tmdb_id, int):
            log.debug("SKIPPING: \'%s (%s)\' blacklisted it has an invalid TMDb ID", movie_title, movie_year)
            return False
        else:
            return True
    except Exception:
        log.exception("Exception validating TMDb ID for \'%s (%s)\'.", movie_title, movie_year)
    return False


def verify_movie_exists_on_tmdb(movie_title, movie_year, movie_tmdb_id):
    # Safety Check: If no API Key is set, return True (Allow) to avoid blocking everything.
    if not TMDB_API_KEY or 'PASTE_YOUR_KEY' in TMDB_API_KEY:
        log.warning("TMDb API Key missing in tmdb.py! Allowing \'%s\' to prevent false blocks.", movie_title)
        return True

    try:
        # Use the Official API (Fast & Reliable)
        url = "https://api.themoviedb.org/3/movie/{}".format(movie_tmdb_id)
        params = {'api_key': TMDB_API_KEY}
        
        req = requests.get(url, params=params, timeout=10)
        
        if req.status_code == 200:
            log.debug("\'%s (%s)\' [TMDb ID: %s] confirmed via API.", movie_title, movie_year, movie_tmdb_id)
            return True
        elif req.status_code == 404:
            log.debug("SKIPPING: \'%s (%s)\' [TMDb ID: %s] does not exist on TMDb (404).", movie_title, movie_year,
                      movie_tmdb_id)
            return False
        else:
            # If the API is down (500) or Rate Limited (429), we assume the movie EXISTS (Fail Open)
            # so we don't accidentally skip a good movie just because the internet hiccuped.
            log.warning("TMDb API returned status %d for \'%s\'. Assuming valid.", req.status_code, movie_title)
            return True

    except Exception:
        log.exception("Exception verifying TMDb ID for \'%s (%s)\'.", movie_title, movie_year)
        # Fail Open on crash
        return True


def check_movie_tmdb_id(movie_title, movie_year, movie_tmdb_id):
    try:
        if validate_movie_tmdb_id(movie_title, movie_year, movie_tmdb_id):
            return verify_movie_exists_on_tmdb(movie_title, movie_year, movie_tmdb_id)
    except Exception:
        log.exception("Exception verifying/validating TMDb ID for \'%s (%s)\'.", movie_title, movie_year)
    
    # If something breaks badly, default to False to be safe, 
    # but the sub-functions are designed to return True on errors now.
    return False
