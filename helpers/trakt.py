from helpers import str as misc_str
from misc.log import logger

log = logger.get_logger(__name__)


def extract_list_user_and_key_from_url(list_url):
    try:
        import re
        list_user = re.search('\/users\/([^/]*)', list_url).group(1)
        list_key = re.search('\/lists\/([^/?]*)', list_url).group(1)

        return list_user, list_key
    except:
        log.error('The URL "%s" is not in the correct format', list_url)
    exit()


# ---------------------------------------------------------
# STANDARD RATING/VOTE CHECKS
# ---------------------------------------------------------

def blacklisted_min_rating(item, min_rating, item_type='show'):
    # Returns True if the item's rating is BELOW the minimum (i.e., blacklisted)
    if not min_rating:
        return False
        
    try:
        rating = item[item_type].get('rating')
        title = item[item_type].get('title', 'Unknown Title')
        
        if rating is None:
            log.debug("Rating check: No rating found for %s, skipping check.", title)
            return False
            
        if float(rating) < float(min_rating):
            log.debug("\'%s\' | Blacklisted Rating Check | Blacklisted because rating %.1f is below min %.1f", 
                      title, float(rating), float(min_rating))
            return True
            
    except Exception:
        log.exception("Exception determining rating blacklist: ")
        
    title = item[item_type].get('title', 'Unknown Title')
    rating = item[item_type].get('rating', 0)
    log.debug("\'%s\' | Blacklisted Rating Check | Passed (Rating: %.1f >= %.1f).", 
              title, float(rating), float(min_rating))
    return False


def blacklisted_min_votes(item, min_votes, item_type='show'):
    if not min_votes:
        return False
        
    try:
        votes = item[item_type].get('votes')
        title = item[item_type].get('title', 'Unknown Title')
        
        if votes is None:
            log.debug("Vote count check: No votes found for %s, skipping check.", title)
            return False
            
        if int(votes) < int(min_votes):
            log.debug("\'%s\' | Blacklisted Vote Check   | Blacklisted because votes %d is below min %d", 
                      title, int(votes), int(min_votes))
            return True
            
    except Exception:
        log.exception("Exception determining vote count blacklist: ")
        
    title = item[item_type].get('title', 'Unknown Title')
    votes = item[item_type].get('votes', 0)
    log.debug("\'%s\' | Blacklisted Vote Check   | Passed (Votes: %d >= %d).", 
              title, int(votes), int(min_votes))
    return False


# ---------------------------------------------------------
# ANIME SPECIFIC CHECKS
# ---------------------------------------------------------

def anime_blacklisted_min_rating(item, min_rating, item_type='show'):
    if not min_rating:
        return False
        
    try:
        rating = item[item_type].get('rating')
        title = item[item_type].get('title', 'Unknown Title')
        
        if rating is None:
            log.debug("Anime Rating check: No rating found for %s, skipping check.", title)
            return False
            
        if float(rating) < float(min_rating):
            log.debug("\'%s\' | Blacklisted Anime Rating Check | Blacklisted because rating %.1f is below anime min %.1f", 
                      title, float(rating), float(min_rating))
            return True
    except Exception:
        log.exception("Exception determining anime rating blacklist: ")
        
    title = item[item_type].get('title', 'Unknown Title')
    rating = item[item_type].get('rating', 0)
    log.debug("\'%s\' | Blacklisted Anime Rating Check | Passed (Rating: %.1f >= %.1f).", 
              title, float(rating), float(min_rating))
    return False


def anime_blacklisted_min_votes(item, min_votes, item_type='show'):
    if not min_votes:
        return False
        
    try:
        votes = item[item_type].get('votes')
        title = item[item_type].get('title', 'Unknown Title')
        
        if votes is None:
            log.debug("Anime Vote check: No votes found for %s, skipping check.", title)
            return False
            
        if int(votes) < int(min_votes):
            log.debug("\'%s\' | Blacklisted Anime Vote Check   | Blacklisted because votes %d is below anime min %d", 
                      title, int(votes), int(min_votes))
            return True
    except Exception:
        log.exception("Exception determining anime vote count blacklist: ")
        
    title = item[item_type].get('title', 'Unknown Title')
    votes = item[item_type].get('votes', 0)
    log.debug("\'%s\' | Blacklisted Anime Vote Check   | Passed (Votes: %d >= %d).", 
              title, int(votes), int(min_votes))
    return False


# ---------------------------------------------------------
# GENERAL CHECKS
# ---------------------------------------------------------

def blacklisted_show_id(show, blacklisted_ids):
    blacklisted = False
    blacklisted_ids = sorted(map(int, blacklisted_ids))
    try:
        ids = show['show'].get('ids', {})
        tvdb_id = ids.get('tvdb')
        
        if tvdb_id and tvdb_id in blacklisted_ids:
            log.debug("\'%s\' | Blacklisted IDs Check          | Blacklisted because it had a blacklisted TVDB ID: %d",
                      show['show'].get('title', 'Unknown'), tvdb_id)
            blacklisted = True
        if not blacklisted:
            log.debug("\'%s\' | Blacklisted IDs Check          | Passed.", show['show'].get('title', 'Unknown'))
    except Exception:
        log.exception("Exception determining if show had a blacklisted TVDB ID %s: ", show)
    return blacklisted


def blacklisted_show_title(show, blacklisted_keywords):
    blacklisted = False
    try:
        title = show['show'].get('title')
        
        if not title:
            log.debug("Blacklisted Titles Check       | Blacklisted show because it had no title: %s", show)
            blacklisted = True
        else:
            for keyword in blacklisted_keywords:
                if keyword.lower() in title.lower():
                    log.debug("\'%s\' | Blacklisted Titles Check       | Blacklisted because it had the title keyword: %s",
                              title, keyword)
                    blacklisted = True
                    break
    except Exception:
        log.exception("Exception determining if show had a blacklisted title %s: ", show)
    return blacklisted


def blacklisted_show_year(show, earliest_year, latest_year):
    blacklisted = False
    try:
        first_aired = show['show'].get('first_aired')
        year = misc_str.get_year_from_timestamp(first_aired) if first_aired else None
        
        if not year:
            log.debug("\'%s\' | Blacklisted Years Check        | Blacklisted because it had no "
                      "first-aired date specified.",
                      show['show'].get('title', 'Unknown'))
            blacklisted = True
        else:
            if int(year) < earliest_year or int(year) > latest_year:
                log.debug("\'%s\' | Blacklisted Years Check        | Blacklisted because it first aired in: %d",
                          show['show'].get('title', 'Unknown'), int(year))
                blacklisted = True
        if not blacklisted:
            log.debug("\'%s\' | Blacklisted Years Check        | Passed.", show['show'].get('title', 'Unknown'))
    except Exception:
        log.exception("Exception determining if show is within min_year and max_year range %s:", show)
    return blacklisted


def blacklisted_show_network(show, networks):
    blacklisted = False
    try:
        current_show_network = show['show'].get('network')

        if not current_show_network:
            log.debug("\'%s\' | Blacklisted Networks Check   | No network specified, skipping network check.",
                      show['show'].get('title', 'Unknown'))
            return False

        for network in networks:
            if network.lower() in current_show_network.lower():
                log.debug("\'%s\' | Blacklisted Networks Check   | Blacklisted because it's from the network: %s",
                          show['show'].get('title', 'Unknown'), current_show_network)
                blacklisted = True
                break
        
        if not blacklisted:
            log.debug("\'%s\' | Blacklisted Networks Check   | Passed.", show['show'].get('title', 'Unknown'))
            
    except Exception:
        log.exception("Exception determining if show is from a blacklisted network %s: ", show)
    return blacklisted


def blacklisted_show_country(show, allowed_countries):
    blacklisted = False
    try:
        country = show['show'].get('country')

        if any('ignore' in s.lower() for s in allowed_countries):
            log.debug("\'%s\' | Blacklisted Countries Check  | Ignored.", show['show'].get('title', 'Unknown'))
        elif not country:
            log.debug("\'%s\' | Blacklisted Countries Check  | Blacklisted because it had no country specified.",
                      show['show'].get('title', 'Unknown'))
            blacklisted = True
        elif not allowed_countries:
            log.debug("\'%s\' | Blacklisted Countries Check  | Skipped.",
                      show['show'].get('title', 'Unknown'))
        elif not any(country.lower() in s.lower() for s in allowed_countries):
            log.debug("\'%s\' | Blacklisted Countries Check  | Blacklisted because it's from the country: %s",
                      show['show'].get('title', 'Unknown'),
                      country.upper())
            blacklisted = True
        if not blacklisted:
            log.debug("\'%s\' | Blacklisted Countries Check  | Passed.", show['show'].get('title', 'Unknown'))
    except Exception:
        log.exception("Exception determining if show was from an allowed country %s: ", show)
    return blacklisted


def blacklisted_show_language(show, allowed_languages):
    blacklisted = False
    try:
        language = show['show'].get('language')

        if any('ignore' in s.lower() for s in allowed_languages):
            log.debug("\'%s\' | Blacklisted Languages Check  | Ignored.", show['show'].get('title', 'Unknown'))
        elif not language:
            log.debug("\'%s\' | Blacklisted Languages Check  | Blacklisted because it had no language specified.",
                      show['show'].get('title', 'Unknown'))
            blacklisted = True
        elif not allowed_languages:
            log.debug("\'%s\' | Blacklisted Languages Check  | Skipped.",
                      show['show'].get('title', 'Unknown'))
        elif not any(language.lower() in c.lower() for c in allowed_languages):
            log.debug("\'%s\' | Blacklisted Languages Check  | Blacklisted because it's in the language: %s",
                      show['show'].get('title', 'Unknown'), language.upper())
            blacklisted = True
        if not blacklisted:
            log.debug("\'%s\' | Blacklisted Languages Check  | Passed.", show['show'].get('title', 'Unknown'))
    except Exception:
        log.exception("Exception determining what language the show was in %s: ", show)
    return blacklisted


def blacklisted_show_genre(show, genres):
    blacklisted = False
    try:
        show_genres = show['show'].get('genres')
        title = show['show'].get('title', 'Unknown')

        if any('ignore' in s.lower() for s in genres):
            log.debug("\'%s\' | Blacklisted Genres Check       | Ignored.", title)
        elif not show_genres:
            log.debug("\'%s\' | Blacklisted Genres Check       | Blacklisted because it had no genre specified.",
                      title)
            blacklisted = True
        elif not genres:
            log.debug("\'%s\' | Blacklisted Genres Check       | Skipped.",
                      title)
        else:
            for genre in genres:
                if genre.lower() in show_genres:
                    log.debug("\'%s\' | Blacklisted Genres Check       | Blacklisted because it was from the genre: %s",
                              title, genre.title())
                    blacklisted = True
                    break
        if not blacklisted:
            log.debug("\'%s\' | Blacklisted Genres Check       | Passed.", title)
    except Exception:
        log.exception("Exception determining if show has a blacklisted genre %s: ", show)
    return blacklisted


def blacklisted_show_runtime(show, lowest_runtime):
    blacklisted = False
    try:
        runtime = show['show'].get('runtime')
        title = show['show'].get('title', 'Unknown')

        if not runtime or not isinstance(runtime, int):
            log.debug("\'%s\' | Blacklisted Runtime Check    | Blacklisted because it had no runtime specified.",
                      title)
            blacklisted = True
        elif int(runtime) < lowest_runtime:
            log.debug("\'%s\' | Blacklisted Runtime Check    | Blacklisted because it had the runtime of: %d min.",
                      title, runtime)
            blacklisted = True
        if not blacklisted:
            log.debug("\'%s\' | Blacklisted Runtime Check    | Passed.", title)
    except Exception:
        log.exception("Exception determining if show had sufficient runtime %s: ", show)
    return blacklisted


def is_show_blacklisted(show, blacklist_settings, ignore_blacklist, callback=None, is_anime=False):
    if ignore_blacklist:
        return False

    blacklisted = False
    try:
        # LOGIC BRANCHING: Use Anime functions if Anime, otherwise Standard
        if is_anime:
            if anime_blacklisted_min_rating(show, blacklist_settings.get('blacklisted_anime_min_rating'), 'show'):
                blacklisted = True
            if anime_blacklisted_min_votes(show, blacklist_settings.get('blacklisted_anime_min_votes'), 'show'):
                blacklisted = True
        else:
            if blacklisted_min_rating(show, blacklist_settings.get('blacklisted_min_rating'), 'show'):
                blacklisted = True
            if blacklisted_min_votes(show, blacklist_settings.get('blacklisted_min_votes'), 'show'):
                blacklisted = True
            
        # EXISTING FILTERS
        if blacklisted_show_id(show, blacklist_settings.get('blacklisted_tvdb_ids', [])):
            blacklisted = True
        if blacklisted_show_title(show, blacklist_settings.get('blacklisted_title_keywords', [])):
            blacklisted = True
        if blacklisted_show_year(show, blacklist_settings.get('blacklisted_min_year', 0),
                                 blacklist_settings.get('blacklisted_max_year', 9999)):
            blacklisted = True
        if blacklisted_show_network(show, blacklist_settings.get('blacklisted_networks', [])):
            blacklisted = True
        if blacklisted_show_country(show, blacklist_settings.get('allowed_countries', [])):
            blacklisted = True
        if blacklisted_show_language(show, blacklist_settings.get('allowed_languages', [])):
            blacklisted = True
        if blacklisted_show_genre(show, blacklist_settings.get('blacklisted_genres', [])):
            blacklisted = True
        if blacklisted_show_runtime(show, blacklist_settings.get('blacklisted_min_runtime', 0)):
            blacklisted = True
        if blacklisted and callback:
            callback('show', show)
    except Exception:
        log.exception("Exception determining if show was blacklisted %s: ", show)
    return blacklisted


def blacklisted_movie_id(movie, blacklisted_ids):
    blacklisted = False
    blacklisted_ids = sorted(map(int, blacklisted_ids))
    try:
        ids = movie['movie'].get('ids', {})
        tmdb_id = ids.get('tmdb')
        title = movie['movie'].get('title', 'Unknown')

        if tmdb_id and tmdb_id in blacklisted_ids:
            log.debug("\'%s\' | Blacklisted IDs Check          | Blacklisted because it had a blacklisted TMDb ID: %d",
                      title, tmdb_id)
            blacklisted = True
        if not blacklisted:
            log.debug("\'%s\' | Blacklisted IDs Check          | Passed.", title)
    except Exception:
        log.exception("Exception determining if movie had a blacklisted TMDb ID %s: ", movie)
    return blacklisted


def blacklisted_movie_title(movie, blacklisted_keywords):
    blacklisted = False
    try:
        title = movie['movie'].get('title')

        if not title:
            log.debug("Blacklisted Titles Check       | Blacklisted movie because it had no title: %s", movie)
            blacklisted = True
        else:
            for keyword in blacklisted_keywords:
                if keyword.lower() in title.lower():
                    log.debug("\'%s\' | Blacklisted Titles Check       | Blacklisted because it had the title keyword: %s",
                              title, keyword)
                    blacklisted = True
                    break
        if not blacklisted:
            log.debug("\'%s\' | Blacklisted Titles Check       | Passed.", title)
    except Exception:
        log.exception("Exception determining if movie had a blacklisted title %s: ", movie)
    return blacklisted


def blacklisted_movie_year(movie, earliest_year, latest_year):
    blacklisted = False
    try:
        year = movie['movie'].get('year')
        title = movie['movie'].get('title', 'Unknown')

        if not year and movie['movie'].get('released'):
            year = misc_str.get_year_from_timestamp(movie['movie']['released'])

        if year is None or not (isinstance(year, int) or (isinstance(year, str) and year.isdigit())):
            log.debug("\'%s\' | Blacklisted Years Check        | Blacklisted because it had no year specified.",
                      title)
            blacklisted = True
        else:
            if int(year) < earliest_year or int(year) > latest_year:
                log.debug("\'%s\' | Blacklisted Years Check        | Blacklisted because its year is: %d",
                          title, int(year))
                blacklisted = True
        if not blacklisted:
            log.debug("\'%s\' | Blacklisted Years Check        | Passed.", title)
    except Exception:
        log.exception("Exception determining if movie is within min_year and max_year ranger %s:", movie)
    return blacklisted


def blacklisted_movie_country(movie, allowed_countries):
    blacklisted = False
    try:
        country = movie['movie'].get('country')

        if any('ignore' in s.lower() for s in allowed_countries):
            log.debug("\'%s\' | Blacklisted Countries Check  | Ignored.",
                      movie['movie'].get('title', 'Unknown'))
        elif not country:
            log.debug("\'%s\' | Blacklisted Countries Check  | Blacklisted because it had no country specified.",
                      movie['movie'].get('title', 'Unknown'))
            blacklisted = True
        elif not allowed_countries:
            log.debug("\'%s\' | Blacklisted Countries Check  | Skipped.",
                      movie['movie'].get('title', 'Unknown'))
        elif not any(country.lower() in s.lower() for s in allowed_countries):
            log.debug("\'%s\' | Blacklisted Countries Check  | Blacklisted because it's from the country: %s",
                      movie['movie'].get('title', 'Unknown'), country.upper())
            blacklisted = True
        if not blacklisted:
            log.debug("\'%s\' | Blacklisted Countries Check  | Passed.", movie['movie'].get('title', 'Unknown'))
    except Exception:
        log.exception("Exception determining if movie was from an allowed country %s: ", movie)
    return blacklisted


def blacklisted_movie_language(movie, allowed_languages):
    blacklisted = False
    try:
        language = movie['movie'].get('language')

        if any('ignore' in s.lower() for s in allowed_languages):
            log.debug("\'%s\' | Blacklisted Languages Check  | Ignored.",
                      movie['movie'].get('title', 'Unknown'))
        elif not language:
            log.debug("\'%s\' | Blacklisted Languages Check  | Blacklisted because it had no language specified.",
                      movie['movie'].get('title', 'Unknown'))
            blacklisted = True
        elif not allowed_languages:
            log.debug("\'%s\' | Blacklisted Languages Check  | Skipped.",
                      movie['movie'].get('title', 'Unknown'))
        elif not any(language.lower() in s.lower() for s in allowed_languages):
            log.debug("\'%s\' | Blacklisted Languages Check  | Blacklisted because it's in the language: %s",
                      movie['movie'].get('title', 'Unknown'), language.upper())
            blacklisted = True
        if not blacklisted:
            log.debug("\'%s\' | Blacklisted Languages Check  | Passed.", movie['movie'].get('title', 'Unknown'))
    except Exception:
        log.exception("Exception determining what language the movie was %s: ", movie)
    return blacklisted


def blacklisted_movie_genre(movie, genres):
    blacklisted = False
    try:
        movie_genres = movie['movie'].get('genres')
        title = movie['movie'].get('title', 'Unknown')

        if any('ignore' in s.lower() for s in genres):
            log.debug("\'%s\' | Blacklisted Genres Check       | Ignored.", title)
        elif not movie_genres:
            log.debug("\'%s\' | Blacklisted Genres Check       | Blacklisted because it had no genre specified.",
                      title)
            blacklisted = True
        elif not genres:
            log.debug("\'%s\' | Blacklisted Genres Check       | Skipped.",
                      title)
        else:
            for genre in genres:
                if genre.lower() in movie_genres:
                    log.debug("\'%s\' | Blacklisted Genres Check       | Blacklisted because it was from the genre: %s",
                              title, genre.title())
                    blacklisted = True
                    break
        if not blacklisted:
            log.debug("\'%s\' | Blacklisted Genres Check       | Passed.", title)
    except Exception:
        log.exception("Exception determining if movie has a blacklisted genre %s: ", movie)
    return blacklisted


def blacklisted_movie_runtime(movie, lowest_runtime):
    blacklisted = False
    try:
        runtime = movie['movie'].get('runtime')
        title = movie['movie'].get('title', 'Unknown')

        if not runtime or not isinstance(runtime, int):
            log.debug("\'%s\' | Blacklisted Runtime Check    | Blacklisted because it had no runtime specified.",
                      title)
            blacklisted = True
        elif int(runtime) < lowest_runtime:
            log.debug("\'%s\' | Blacklisted Runtime Check    | Blacklisted because it had the runtime of: %d min.",
                      title, runtime)
            blacklisted = True
        if not blacklisted:
            log.debug("\'%s\' | Blacklisted Runtime Check    | Passed.", title)
    except Exception:
        log.exception("Exception determining if movie had sufficient runtime %s: ", movie)
    return blacklisted


def is_movie_blacklisted(movie, blacklist_settings, ignore_blacklist, callback=None, is_anime=False):
    if ignore_blacklist:
        return False

    blacklisted = False
    try:
        # LOGIC BRANCHING: Use Anime functions if Anime, otherwise Standard
        if is_anime:
            if anime_blacklisted_min_rating(movie, blacklist_settings.get('blacklisted_anime_min_rating'), 'movie'):
                blacklisted = True
            if anime_blacklisted_min_votes(movie, blacklist_settings.get('blacklisted_anime_min_votes'), 'movie'):
                blacklisted = True
        else:
            if blacklisted_min_rating(movie, blacklist_settings.get('blacklisted_min_rating'), 'movie'):
                blacklisted = True
            if blacklisted_min_votes(movie, blacklist_settings.get('blacklisted_min_votes'), 'movie'):
                blacklisted = True
            
        # EXISTING FILTERS
        if blacklisted_movie_id(movie, blacklist_settings.get('blacklisted_tmdb_ids', [])):
            blacklisted = True
        if blacklisted_movie_title(movie, blacklist_settings.get('blacklisted_title_keywords', [])):
            blacklisted = True
        if blacklisted_movie_year(movie, blacklist_settings.get('blacklisted_min_year', 0),
                                  blacklist_settings.get('blacklisted_max_year', 9999)):
            blacklisted = True
        if blacklisted_movie_country(movie, blacklist_settings.get('allowed_countries', [])):
            blacklisted = True
        if blacklisted_movie_language(movie, blacklist_settings.get('allowed_languages', [])):
            blacklisted = True
        if blacklisted_movie_genre(movie, blacklist_settings.get('blacklisted_genres', [])):
            blacklisted = True
        if blacklisted_movie_runtime(movie, blacklist_settings.get('blacklisted_min_runtime', 0)):
            blacklisted = True
        if blacklisted and callback:
            callback('movie', movie)
    except Exception:
        log.exception("Exception determining if movie was blacklisted %s: ", movie)
    return blacklisted
