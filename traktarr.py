#!/usr/bin/env python3
import os.path
import signal
import sys
import time
import datetime
import requests
import click
import schedule
from pyfiglet import Figlet

############################################################
# INIT
############################################################
cfg = None
log = None
notify = None
run_stats = {'movies': [], 'shows': []}  # Added for Run Summary


# Click
@click.group(help='Add new shows & movies to Sonarr/Radarr from Trakt.')
@click.version_option('1.2.5', prog_name='Traktarr')
@click.option(
    '--config',
    envvar='TRAKTARR_CONFIG',
    type=click.Path(file_okay=True, dir_okay=False),
    help='Configuration file',
    show_default=True,
    default=os.path.join(os.path.dirname(os.path.realpath(sys.argv[0])), "config.json")
)
@click.option(
    '--cachefile',
    envvar='TRAKTARR_CACHEFILE',
    type=click.Path(file_okay=True, dir_okay=False),
    help='Cache file',
    show_default=True,
    default=os.path.join(os.path.dirname(os.path.realpath(sys.argv[0])), "cache.db")
)
@click.option(
    '--logfile',
    envvar='TRAKTARR_LOGFILE',
    type=click.Path(file_okay=True, dir_okay=False),
    help='Log file',
    show_default=True,
    default=os.path.join(os.path.dirname(os.path.realpath(sys.argv[0])), "activity.log")
)
def app(config, cachefile, logfile):
    # Setup global variables
    global cfg, log, notify

    # Load config
    from misc.config import Config
    cfg = Config(configfile=config, cachefile=cachefile, logfile=logfile).cfg

    # Legacy Support
    if cfg.filters.movies.blacklist_title_keywords:
        cfg['filters']['movies']['blacklisted_title_keywords'] = cfg['filters']['movies']['blacklist_title_keywords']
    if cfg.filters.movies.rating_limit:
        cfg['filters']['movies']['rotten_tomatoes'] = cfg['filters']['movies']['rating_limit']
    if cfg.radarr.profile:
        cfg['radarr']['quality'] = cfg['radarr']['profile']
    if cfg.sonarr.profile:
        cfg['sonarr']['quality'] = cfg['sonarr']['profile']

    # Load logger
    from misc.log import logger
    log = logger.get_logger('Traktarr')

    # Load notifications
    from notifications import Notifications
    notify = Notifications()

    # Notifications
    init_notifications()


############################################################
# Trakt OAuth
############################################################

@app.command(help='Authenticate Traktarr.')
def trakt_authentication():
    from media.trakt import Trakt
    trakt = Trakt(cfg)

    if trakt.oauth_authentication():
        log.info("Authentication information saved. Please restart the application.")
        exit()


def validate_trakt(trakt, notifications):
    log.info("Validating Trakt API Key...")
    if not trakt.validate_client_id():
        log.error("Aborting due to failure to validate Trakt API Key")
        if notifications:
            callback_notify({'event': 'error', 'reason': 'Failure to validate Trakt API Key'})
        exit()
    else:
        log.info("...Validated Trakt API Key.")


def validate_pvr(pvr, pvr_type, notifications):
    if not pvr.validate_api_key():
        log.error("Aborting due to failure to validate %s URL / API Key", pvr_type)
        if notifications:
            callback_notify({'event': 'error', 'reason': 'Failure to validate %s URL / API Key' % pvr_type})
        return None
    else:
        log.info("Validated %s URL & API Key.", pvr_type)


def get_quality_profile_id(pvr, quality_profile):
    # retrieve profile id for requested quality profile
    quality_profile_id = pvr.get_quality_profile_id(quality_profile)
    if not quality_profile_id or quality_profile_id <= 0:
        log.error("Aborting due to failure to retrieve Quality Profile ID for: %s", quality_profile)
        exit()
    log.info("Retrieved Quality Profile ID for \'%s\': %d", quality_profile, quality_profile_id)
    return quality_profile_id


def get_profile_tags(pvr):
    profile_tags = pvr.get_tags()
    if profile_tags is None:
        log.error("Aborting due to failure to retrieve Tag IDs")
        exit()
    log.info("Retrieved Sonarr Tag IDs: %d", len(profile_tags))
    return profile_tags


def get_objects(pvr, pvr_type, notifications):
    objects_list = pvr.get_objects()
    objects_type = 'movies' if pvr_type.lower() == 'radarr' else 'shows'
    if not objects_list:
        log.error("Aborting due to failure to retrieve %s list from %s", objects_type, pvr_type)
        if notifications:
            callback_notify({'event': 'error', 'reason': 'Failure to retrieve \'%s\' list from %s' % (objects_type,
                                                                                                      pvr_type)})
        exit()
    log.info("Retrieved %s %s list, %s found: %d", pvr_type, objects_type, objects_type, len(objects_list))
    return objects_list


def get_exclusions(pvr, pvr_type):
    objects_list = pvr.get_exclusions()
    objects_type = 'movie' if pvr_type.lower() == 'radarr' else 'show'
    if not objects_list:
        log.info("No %s exclusions list found from %s", objects_type, pvr_type)
    log.info("Retrieved %s %s list, %s found: %d", pvr_type, objects_type, objects_type, len(objects_list))
    return objects_list


############################################################
# SHOWS
############################################################

@app.command(help='Add a single show to Sonarr.', context_settings=dict(max_content_width=100))
@click.option(
    '--show-id', '-id',
    help='Trakt Show ID.',
    required=True)
@click.option(
    '--folder', '-f',
    default=None,
    help='Add show with this root folder to Sonarr.')
@click.option(
    '--no-search',
    is_flag=True,
    help='Disable search when adding show to Sonarr.')
def show(
        show_id,
        folder=None,
        no_search=False,
):

    from media.sonarr import Sonarr
    from media.trakt import Trakt
    from helpers import sonarr as sonarr_helper
    from helpers import str as misc_str

    # replace sonarr root_folder if folder is supplied
    if folder:
        cfg['sonarr']['root_folder'] = folder

    trakt = Trakt(cfg)
    sonarr = Sonarr(cfg.sonarr.url, cfg.sonarr.api_key)

    validate_trakt(trakt, False)
    validate_pvr(sonarr, 'Sonarr', False)

    # get trakt show
    trakt_show = trakt.get_show(show_id)

    if not trakt_show:
        log.error("Aborting due to failure to retrieve Trakt show")
        return None

    # set common series variables
    series_title = trakt_show.get('title')

    # convert series year to string
    year_data = trakt_show.get('year')
    if year_data:
        series_year = str(year_data)
    elif trakt_show.get('first_aired'):
        series_year = misc_str.get_year_from_timestamp(trakt_show['first_aired'])
    else:
        series_year = '????'

    log.info("Retrieved Trakt show information for \'%s\': \'%s (%s)\'", show_id, series_title, series_year)

    # quality profile id
    quality_profile_id = get_quality_profile_id(sonarr, cfg.sonarr.quality)

    # profile tags
    profile_tags = None
    tag_ids = None
    tag_names = None

    if cfg.sonarr.tags is not None:
        profile_tags = get_profile_tags(sonarr)
        if profile_tags is not None:
            # determine which tags to use when adding this series
            tag_ids = sonarr_helper.series_tag_ids_list_builder(
                profile_tags,
                cfg.sonarr.tags,
            )
            tag_names = sonarr_helper.series_tag_names_list_builder(
                profile_tags,
                tag_ids,
            )

    # series type
    genres_list = trakt_show.get('genres', [])
    if any('anime' in s.lower() for s in genres_list):
        series_type = 'anime'
    else:
        series_type = 'standard'

    log.debug("Set series type for \'%s (%s)\' to: %s", series_title, series_year, series_type.title())

    # add show to sonarr
    if sonarr.add_series(
            trakt_show['ids']['tvdb'],
            series_title,
            trakt_show['ids']['slug'],
            quality_profile_id,
            cfg.sonarr.root_folder,
            cfg.sonarr.season_folder,
            tag_ids,
            not no_search,
            series_type,
    ):

        if profile_tags is not None and tag_names is not None:
            log.info("ADDED: \'%s (%s)\' with Sonarr Tags: %s", series_title, series_year,
                     tag_names)
        else:
            log.info("ADDED: \'%s (%s)\'", series_title, series_year)
    elif profile_tags is not None:
        log.error("FAILED ADDING: \'%s (%s)\' with Sonarr Tags: %s", series_title, series_year,
                  tag_names)
    else:
        log.info("FAILED ADDING: \'%s (%s)\'", series_title, series_year)

    return


@app.command(help='Add multiple shows to Sonarr.', context_settings=dict(max_content_width=100))
@click.option(
    '--list-type', '-t',
    help='Trakt list to process. '
         'For example, \'anticipated\', \'trending\', \'popular\', \'person\', \'watched\', \'played\', '
         '\'recommended\', \'watchlist\', or any URL to a list.',
    required=True)
@click.option(
    '--add-limit', '-l',
    default=0,
    help='Limit number of shows added to Sonarr.')
@click.option(
    '--add-delay', '-d',
    default=2.5,
    help='Seconds between each add request to Sonarr.',
    show_default=True)
@click.option(
    '--sort', '-s',
    default='votes',
    type=click.Choice(['rating', 'release', 'votes']),
    help='Sort list to process.',
    show_default=True)
@click.option(
    '--year', '--years', '-y',
    default=None,
    help='Can be a specific year or a range of years to search. For example, \'2000\' or \'2000-2010\'.')
@click.option(
    '--genres', '-g',
    default=None,
    help='Only add shows from this genre to Sonarr. '
         'Multiple genres are specified as a comma-separated list. '
         'Use \'ignore\' to add shows from any genre, including ones with no genre specified.')
@click.option(
    '--folder', '-f',
    default=None,
    help='Add shows with this root folder to Sonarr.')
@click.option(
    '--person', '-p',
    default=None,
    help='Only add shows from this person (e.g. actor) to Sonarr. '
         'Only one person can be specified. '
         'Requires the \'person\' list type.')
@click.option(
    '--include-non-acting-roles',
    is_flag=True,
    help='Include non-acting roles such as \'Director\', \'As Himself\', \'Narrator\', etc. '
         'Requires the \'person\' list type with the \'person\' argument.')
@click.option(
    '--no-search',
    is_flag=True,
    help='Disable search when adding shows to Sonarr.')
@click.option(
    '--notifications',
    is_flag=True,
    help='Send notifications.')
@click.option(
    '--authenticate-user',
    help='Specify which user to authenticate with to retrieve Trakt lists. '
         'Defaults to first user in the config')
@click.option(
    '--ignore-blacklist',
    is_flag=True,
    help='Ignores the blacklist when running the command.')
@click.option(
    '--remove-rejected-from-recommended',
    is_flag=True,
    help='Removes rejected/existing shows from recommended.')
@click.option(
    '--dry-run',
    is_flag=True,
    help='Shows the list of shows remaining after processing, takes no action on them.')
def shows(
        list_type,
        add_limit=0,
        add_delay=2.5,
        sort='votes',
        years=None,
        genres=None,
        folder=None,
        person=None,
        no_search=False,
        include_non_acting_roles=False,
        notifications=False,
        authenticate_user=None,
        ignore_blacklist=False,
        remove_rejected_from_recommended=False,
        dry_run=False,
):

    from media.sonarr import Sonarr
    from media.trakt import Trakt
    from helpers import str as misc_str
    from helpers import misc as misc_helper
    from helpers import sonarr as sonarr_helper
    from helpers import trakt as trakt_helper
    from helpers import tvdb as tvdb_helper
    from helpers import parameter as parameter_helper

    added_shows = 0

    # -------------------------------------------------------------
    # DYNAMIC YEAR LOGIC
    # -------------------------------------------------------------
    max_year = cfg.filters.shows.get('blacklisted_max_year')
    if max_year is None or max_year == "":
        current_year = datetime.datetime.now().year
        cfg['filters']['shows']['blacklisted_max_year'] = current_year
        log.debug("Dynamic Config: 'blacklisted_max_year' (Missing/Empty) set to Current Year (%s)", current_year)
    # -------------------------------------------------------------

    # --- UPDATED: Retrieve config filters but DON'T send to API ---
    config_countries = None
    if cfg.filters.shows.allowed_countries and 'ignore' not in cfg.filters.shows.allowed_countries:
        config_countries = cfg.filters.shows.allowed_countries

    config_languages = None
    if cfg.filters.shows.allowed_languages and 'ignore' not in cfg.filters.shows.allowed_languages:
        config_languages = cfg.filters.shows.allowed_languages

    # process genres
    if genres:
        # split comma separated list
        genres = sorted(genres.split(','), key=str.lower)

        # look for special keyword 'ignore'
        if 'ignore' in genres:
            # set special genre keyword to show's blacklisted_genres list
            cfg['filters']['shows']['blacklisted_genres'] = ['ignore']
            genres = None
        else:
            # remove genres from show's blacklisted_genres list
            misc_helper.unblacklist_genres(genres, cfg['filters']['shows']['blacklisted_genres'])
            log.debug("Filter Trakt results with genre(s): %s", ', '.join(map(lambda x: x.title(), genres)))

    # process years parameter
    years, new_min_year, new_max_year = parameter_helper.years(
        years,
        cfg.filters.shows.blacklisted_min_year,
        cfg.filters.shows.blacklisted_max_year,
    )

    cfg['filters']['shows']['blacklisted_min_year'] = new_min_year
    cfg['filters']['shows']['blacklisted_max_year'] = new_max_year

    # runtimes range
    if cfg.filters.shows.blacklisted_min_runtime:
        min_runtime = cfg.filters.shows.blacklisted_min_runtime
    else:
        min_runtime = 0

    if cfg.filters.shows.blacklisted_max_runtime and cfg.filters.shows.blacklisted_max_runtime >= min_runtime:
        max_runtime = cfg.filters.shows.blacklisted_max_runtime
    else:
        max_runtime = 9999

    if min_runtime == 0 and max_runtime == 9999:
        runtimes = None
    else:
        runtimes = str(min_runtime) + '-' + str(max_runtime)

    # replace sonarr root_folder if folder is supplied
    if folder:
        cfg['sonarr']['root_folder'] = folder

    # validate trakt client_id
    trakt = Trakt(cfg)
    sonarr = Sonarr(cfg.sonarr.url, cfg.sonarr.api_key)

    validate_trakt(trakt, notifications)
    validate_pvr(sonarr, 'Sonarr', notifications)

    # quality profile id
    quality_profile_id = get_quality_profile_id(sonarr, cfg.sonarr.quality)
    
    # Feature: Fetch Anime Quality Profile ID if configured
    anime_quality_profile_id = None
    if cfg.sonarr.get('anime_quality_profile'):
        anime_quality_profile_id = get_quality_profile_id(sonarr, cfg.sonarr.anime_quality_profile)

    # profile tags
    profile_tags = None
    tag_ids = None
    tag_names = None
    anime_tag_id = None # Store anime tag ID if found

    if cfg.sonarr.tags is not None:
        profile_tags = get_profile_tags(sonarr)
        if profile_tags is not None:
            # determine which tags to use when adding this series
            tag_ids = sonarr_helper.series_tag_ids_list_builder(
                profile_tags,
                cfg.sonarr.tags,
            )
            tag_names = sonarr_helper.series_tag_names_list_builder(
                profile_tags,
                tag_ids,
            )
            
            # Feature: Resolve Anime Tag ID from Config Name
            if cfg.sonarr.get('anime_tag_name'):
                anime_tag_name = cfg.sonarr.anime_tag_name.lower()
                if anime_tag_name in profile_tags:
                    anime_tag_id = profile_tags[anime_tag_name]
                    log.debug("Found Anime Tag ID for '%s': %s", anime_tag_name, anime_tag_id)
                else:
                    log.warning("Anime Tag '%s' not found in Sonarr.", anime_tag_name)

    pvr_objects_list = get_objects(sonarr, 'Sonarr', notifications)

    # get trakt series list
    # UPDATED: We pass None for countries/languages to API, so we get everything
    if list_type.lower() == 'anticipated':
        trakt_objects_list = trakt.get_anticipated_shows(
            years=years,
            countries=None,
            languages=None,
            genres=genres,
            runtimes=runtimes,
        )

    elif list_type.lower() == 'trending':
        trakt_objects_list = trakt.get_trending_shows(
            years=years,
            countries=None,
            languages=None,
            genres=genres,
            runtimes=runtimes,
        )

    elif list_type.lower() == 'popular':
        trakt_objects_list = trakt.get_popular_shows(
            years=years,
            countries=None,
            languages=None,
            genres=genres,
            runtimes=runtimes,
        )

    elif list_type.lower() == 'person':
        if not person:
            log.error("You must specify an person with the \'--person\' / \'-p\' parameter when using the \'person\'" +
                      " list type!")
            return None
        trakt_objects_list = trakt.get_person_shows(
            years=years,
            person=person,
            countries=None,
            languages=None,
            genres=genres,
            runtimes=runtimes,
            include_non_acting_roles=include_non_acting_roles,
        )

    elif list_type.lower() == 'recommended':
        trakt_objects_list = trakt.get_recommended_shows(
            authenticate_user,
            years=years,
            countries=None,
            languages=None,
            genres=genres,
            runtimes=runtimes,
        )

    elif list_type.lower().startswith('played'):
        most_type = misc_helper.substring_after(list_type.lower(), "_")
        trakt_objects_list = trakt.get_most_played_shows(
            years=years,
            countries=None,
            languages=None,
            genres=genres,
            runtimes=runtimes,
            most_type=most_type if most_type else None,
        )

    elif list_type.lower().startswith('watched'):
        most_type = misc_helper.substring_after(list_type.lower(), "_")
        trakt_objects_list = trakt.get_most_watched_shows(
            years=years,
            countries=None,
            languages=None,
            genres=genres,
            runtimes=runtimes,
            most_type=most_type if most_type else None,
        )

    elif list_type.lower() == 'watchlist':
        trakt_objects_list = trakt.get_watchlist_shows(authenticate_user)
    else:
        trakt_objects_list = trakt.get_user_list_movies(list_type, authenticate_user)

    if not trakt_objects_list:
        log.error("Aborting due to failure to retrieve Trakt \'%s\' shows list.", list_type.capitalize())
        if notifications:
            callback_notify(
                {'event': 'abort', 'type': 'shows', 'list_type': list_type,
                 'reason': 'Failure to retrieve Trakt \'%s\' shows list.' % list_type.capitalize()})
        return None
    else:
        log.info("Retrieved Trakt \'%s\' shows list, shows found: %d", list_type.capitalize(), len(trakt_objects_list))

    # set remove_rejected_recommended to False if this is not the recommended list
    if list_type.lower() != 'recommended':
        remove_rejected_from_recommended = False

    # build filtered series list without series that exist in sonarr
    processed_series_list = sonarr_helper.remove_existing_series_from_trakt_list(
        pvr_objects_list,
        trakt_objects_list,
        callback_remove_recommended if remove_rejected_from_recommended else None
    )

    if processed_series_list is None:
        log.error("Aborting due to failure to remove existing Sonarr shows from retrieved Trakt shows list.")
        if notifications:
            callback_notify({'event': 'abort', 'type': 'shows', 'list_type': list_type,
                             'reason': 'Failure to remove existing Sonarr shows from retrieved Trakt \'%s\' shows list.'
                                       % list_type.capitalize()})
        return None
    else:
        log.info("Removed existing Sonarr shows from Trakt shows list, shows left to process: %d",
                 len(processed_series_list))

    # sort filtered series list
    if sort == 'release':
        sorted_series_list = misc_helper.sorted_list(processed_series_list, 'show', 'first_aired')
        log.info("Sorted shows list to process by recent 'release' date.")
    elif sort == 'rating':
        sorted_series_list = misc_helper.sorted_list(processed_series_list, 'show', 'rating')
        log.info("Sorted shows list to process by highest 'rating'.")
    else:
        sorted_series_list = misc_helper.sorted_list(processed_series_list, 'show', 'votes')
        log.info("Sorted shows list to process by highest 'votes'.")

    # loop series_list
    log.info("Processing list now...")
    for series in sorted_series_list:
        # noinspection PyBroadException

        # set common series variables
        series_tvdb_id = series['show']['ids']['tvdb']
        series_title = series['show']['title']

        # convert series year to string
        # Feature 1: Safe .get() included
        year_data = series['show'].get('year')
        if year_data:
            series_year = str(year_data)
        elif series['show'].get('first_aired'):
            series_year = misc_str.get_year_from_timestamp(series['show']['first_aired'])
        else:
            series_year = '????'

        # series type & folder & tags logic
        genres_list = series['show'].get('genres', [])
        
        # Prepare Defaults
        final_root_folder = cfg.sonarr.root_folder
        final_tags = list(tag_ids) if tag_ids else [] # Copy list to avoid modifying global default
        final_quality_profile_id = quality_profile_id # Default Quality
        
        # --- SMART ANIME DETECTION ---
        is_anime = False
        if any('anime' in s.lower() for s in genres_list):
            is_anime = True
            series_type = 'anime'
            
            # Switch to Anime Folder if configured
            if cfg.sonarr.get('anime_root_folder'):
                final_root_folder = cfg.sonarr.anime_root_folder
                
            # Append Anime Tag if configured and found
            if anime_tag_id:
                if anime_tag_id not in final_tags:
                    final_tags.append(anime_tag_id)
            
            # Switch Quality Profile if configured
            if anime_quality_profile_id:
                final_quality_profile_id = anime_quality_profile_id
        else:
            series_type = 'standard'

        log.debug("Set series type for \'%s (%s)\' to: %s", series_title, series_year, series_type.title())

        # build list of genres
        series_genres = (', '.join(genres_list)).title() if genres_list else 'N/A'

        try:
            # --- 0. MANUAL GENRE CHECK (Universal Override) ---
            # Explicitly checks genres against config for ALL content (Standard & Anime)
            blacklisted_genres = cfg.filters.shows.get('blacklisted_genres', [])
            if blacklisted_genres:
                bad_genres = [g for g in genres_list if g.lower() in blacklisted_genres]
                if bad_genres:
                     log.info("SKIPPED: '%s' (Blacklisted Genre: %s)", series_title, ', '.join(bad_genres))
                     continue

            # --- LOCAL FILTERING (The "Anime Exception" Logic) ---
            # 1. Check Languages
            if config_languages:
                show_lang = (series['show'].get('language') or '').lower()
                if show_lang not in config_languages:
                    if not is_anime:
                        log.debug("SKIPPED: '%s' (Language '%s' not allowed)", series_title, show_lang)
                        continue
            
            # 2. Check Countries (Skip this local check - delegated to helper for Anime)
            if not is_anime and config_countries:
                show_country = (series['show'].get('country') or '').lower()
                # Standard content must match allowed_countries
                if show_country not in config_countries:
                     log.debug("SKIPPED: '%s' (Country '%s' not allowed)", series_title, show_country)
                     continue

            # 3. Check Genres (Standard Logic - Redundant but harmless)
            if genres and not misc_helper.allowed_genres(genres, 'show', series):
                log.debug("SKIPPING: \'%s (%s)\' because it was not from the genre(s): %s", series_title,
                          series_year, ', '.join(map(lambda x: x.title(), genres)))
                continue

            # 4. Check blacklist (With Configurable Anime Exception)
            
            # Create a clean copy of filters to modify for this specific check
            current_filters = cfg.filters.shows.copy()
            if is_anime:
                # --- SIMPLIFIED LOGIC ---
                # We simply force the allowed countries to be ['jp'].
                # The helper function will then reject anything that isn't 'jp'.
                current_filters['allowed_countries'] = ['jp']
                current_filters['allowed_languages'] = ['ja'] # Added to fix language blocking

                # Votes (STRICT SEPARATION: Only use Anime limit, or 0/Disable if not set)
                anime_votes = cfg.filters.shows.get('blacklisted_anime_min_votes')
                if anime_votes is not None and anime_votes != "":
                    current_filters['blacklisted_min_votes'] = int(anime_votes)
                else:
                    current_filters['blacklisted_min_votes'] = 0 # Explicitly disable
                
                # Rating (STRICT SEPARATION: Only use Anime limit, or 0.0/Disable if not set)
                anime_rating = cfg.filters.shows.get('blacklisted_anime_min_rating')
                if anime_rating is not None and anime_rating != "":
                    current_filters['blacklisted_min_rating'] = float(anime_rating)
                else:
                    current_filters['blacklisted_min_rating'] = 0.0 # Explicitly disable
            
            if trakt_helper.is_show_blacklisted(
                    series,
                    current_filters,  # PASS MODIFIED FILTERS
                    ignore_blacklist,
                    callback_remove_recommended if remove_rejected_from_recommended else None,
                    is_anime=is_anime
            ):
                log.info("SKIPPED: \'%s (%s)\'", series_title, series_year)
                continue

            # 5. Check if show has a valid TVDB ID and that it exists on TVDB (Network Call)
            if not tvdb_helper.check_series_tvdb_id(series_title, series_year, series_tvdb_id):
                continue

            # 6. Proceed to Add
            log.info("ADDING: %s (%s) | Country: %s | Language: %s | Genre(s): %s | Network: %s",
                     series_title,
                     series_year,
                     (series['show'].get('country', 'N/A') or 'N/A').upper(),
                     (series['show'].get('language', 'N/A') or 'N/A').upper(),
                     series_genres,
                     (series['show'].get('network', 'N/A') or 'N/A').upper(),
             )

            if dry_run:
                log.info("dry-run: SKIPPING")
            else:
                # add show to sonarr
                if sonarr.add_series(
                        series['show']['ids']['tvdb'],
                        series_title,
                        series['show']['ids']['slug'],
                        final_quality_profile_id, # Use dynamic quality
                        final_root_folder,        # Use dynamic folder
                        cfg.sonarr.season_folder,
                        final_tags,               # Use dynamic tags
                        not no_search,
                        series_type,
                ):

                    if profile_tags is not None and tag_names is not None:
                        log.info("ADDED: \'%s (%s)\' with Sonarr Tags: %s", series_title, series_year,
                                 tag_names)
                    else:
                        log.info("ADDED: \'%s (%s)\'", series_title, series_year)
                    
                    # Feature 5: Record Stats for Summary
                    # FIXED: Storing Object, not String
                    # FIXED: Added Destination Folder to object for verification
                    series['root_folder'] = final_root_folder
                    run_stats['shows'].append(series)

                    if notifications:
                        callback_notify({'event': 'add_show', 'list_type': list_type, 'show': series['show']})
                    added_shows += 1
                else:
                    if profile_tags is not None:
                        log.error("FAILED ADDING: \'%s (%s)\' with Sonarr Tags: %s", series_title, series_year,
                                  tag_names)
                    else:
                        log.info("FAILED ADDING: \'%s (%s)\'", series_title, series_year)
                    continue

            # stop adding shows, if added_shows >= add_limit
            if add_limit and added_shows >= add_limit:
                break

            # sleep before adding any more
            time.sleep(add_delay)

        except Exception:
            log.exception("Exception while processing show \'%s\': ", series_title)

    log.info("Added %d new show(s) to Sonarr", added_shows)

    # send notification
    if notifications and (cfg.notifications.verbose or added_shows > 0):
        notify.send(message="Added %d shows from Trakt's \'%s\' list" % (added_shows, list_type))

    return added_shows


############################################################
# MOVIES
############################################################

@app.command(help='Add a single movie to Radarr.', context_settings=dict(max_content_width=100))
@click.option(
    '--movie-id', '-id',
    help='Trakt Movie ID.',
    required=True)
@click.option(
    '--folder', '-f',
    default=None,
    help='Add movie with this root folder to Radarr.')
@click.option(
    '--minimum-availability', '-ma',
    type=click.Choice(['announced', 'in_cinemas', 'released']),
    help='Add movies with this minimum availability to Radarr. Default is \'released\'.')
@click.option(
    '--no-search',
    is_flag=True,
    help='Disable search when adding movie to Radarr.')
def movie(
        movie_id,
        folder=None,
        minimum_availability=None,
        no_search=False,
):

    from media.radarr import Radarr
    from media.trakt import Trakt

    # replace radarr root_folder if folder is supplied
    if folder:
        cfg['radarr']['root_folder'] = folder
    log.debug('Set root folder to: \'%s\'', cfg['radarr']['root_folder'])

    # replace radarr.minimum_availability if minimum_availability is supplied
    valid_min_avail = ['announced', 'in_cinemas', 'released']

    if minimum_availability:
        cfg['radarr']['minimum_availability'] = minimum_availability
    elif cfg['radarr']['minimum_availability'] not in valid_min_avail:
        cfg['radarr']['minimum_availability'] = 'released'

    log.debug('Set minimum availability to: \'%s\'', cfg['radarr']['minimum_availability'])

    # validate trakt api_key
    trakt = Trakt(cfg)
    radarr = Radarr(cfg.radarr.url, cfg.radarr.api_key)

    validate_trakt(trakt, False)
    validate_pvr(radarr, 'Radarr', False)

    # quality profile id
    quality_profile_id = get_quality_profile_id(radarr, cfg.radarr.quality)

    # get trakt movie
    trakt_movie = trakt.get_movie(movie_id)

    if not trakt_movie:
        log.error("Aborting due to failure to retrieve Trakt movie")
        return None

    # convert movie year to string
    # Feature 1: Safe .get() included
    year_data = trakt_movie.get('year')
    movie_year = str(year_data) if year_data else '????'

    log.info("Retrieved Trakt movie information for \'%s\': \'%s (%s)\'", movie_id, trakt_movie['title'], movie_year)

    # add movie to radarr
    if radarr.add_movie(
            trakt_movie['ids']['tmdb'],
            trakt_movie['title'],
            trakt_movie['year'],
            trakt_movie['ids']['slug'],
            quality_profile_id,
            cfg.radarr.root_folder,
            cfg.radarr.minimum_availability,
            not no_search,
    ):

        log.info("ADDED \'%s (%s)\'", trakt_movie['title'], movie_year)
    else:
        log.error("FAILED ADDING \'%s (%s)\'", trakt_movie['title'], movie_year)

    return


@app.command(help='Add multiple movies to Radarr.', context_settings=dict(max_content_width=100))
@click.option(
    '--list-type', '-t',
    help='Trakt list to process. '
         'For example, \'anticipated\', \'trending\', \'popular\', \'person\', \'watched\', \'played\', '
         '\'recommended\', \'watchlist\', or any URL to a list.',
    required=True)
@click.option(
    '--add-limit', '-l',
    default=0,
    help='Limit number of movies added to Radarr.')
@click.option(
    '--add-delay', '-d',
    default=2.5,
    help='Seconds between each add request to Radarr.',
    show_default=True)
@click.option(
    '--sort', '-s',
    default='votes',
    type=click.Choice(['rating', 'release', 'votes']),
    help='Sort list to process.', show_default=True)
@click.option(
    '--rotten_tomatoes', '-rt',
    default=None,
    type=int,
    help='Set a minimum Rotten Tomatoes score.')
@click.option(
    '--year', '--years', '-y',
    default=None,
    help='Can be a specific year or a range of years to search. For example, \'2000\' or \'2000-2010\'.')
@click.option(
    '--genres', '-g',
    default=None,
    help='Only add movies from this genre to Radarr. '
         'Multiple genres are specified as a comma-separated list. '
         'Use \'ignore\' to add movies from any genre, including ones with no genre specified.')
@click.option(
    '--folder', '-f',
    default=None,
    help='Add movies with this root folder to Radarr.')
@click.option(
    '--minimum-availability', '-ma',
    type=click.Choice(['announced', 'in_cinemas', 'released']),
    help='Add movies with this minimum availability to Radarr. Default is \'released\'.')
@click.option(
    '--person', '-p',
    default=None,
    help='Only add movies from this person (e.g. actor) to Radarr. '
         'Only one person can be specified. '
         'Requires the \'person\' list type.')
@click.option(
    '--include-non-acting-roles',
    is_flag=True,
    help='Include non-acting roles such as \'Director\', \'As Himself\', \'Narrator\', etc. '
         'Requires the \'person\' list type with the \'person\' argument.')
@click.option(
    '--no-search',
    is_flag=True,
    help='Disable search when adding movies to Radarr.')
@click.option(
    '--notifications',
    is_flag=True,
    help='Send notifications.')
@click.option(
    '--authenticate-user',
    help='Specify which user to authenticate with to retrieve Trakt lists. '
         'Defaults to first user in the config.')
@click.option(
    '--ignore-blacklist',
    is_flag=True,
    help='Ignores the blacklist when running the command.')
@click.option(
    '--remove-rejected-from-recommended',
    is_flag=True,
    help='Removes rejected/existing movies from recommended.')
@click.option(
    '--dry-run',
    is_flag=True,
    help='Shows the list of movies remaining after processing, takes no action on them.')
def movies(
        list_type,
        add_limit=0,
        add_delay=2.5,
        sort='votes',
        rotten_tomatoes=None,
        years=None,
        genres=None,
        folder=None,
        minimum_availability=None,
        person=None,
        include_non_acting_roles=False,
        no_search=False,
        notifications=False,
        authenticate_user=None,
        ignore_blacklist=False,
        remove_rejected_from_recommended=False,
        dry_run=False,
):

    from media.radarr import Radarr
    from media.trakt import Trakt
    from helpers import misc as misc_helper
    from helpers import radarr as radarr_helper
    from helpers import trakt as trakt_helper
    from helpers import omdb as omdb_helper
    from helpers import tmdb as tmdb_helper
    from helpers import parameter as parameter_helper

    added_movies = 0

    # -------------------------------------------------------------
    # DYNAMIC YEAR LOGIC
    # If blacklisted_max_year is empty ("") or None, update it to Current Year
    # -------------------------------------------------------------
    max_year = cfg.filters.movies.get('blacklisted_max_year')
    if max_year == "" or max_year is None:
        current_year = datetime.datetime.now().year
        cfg['filters']['movies']['blacklisted_max_year'] = current_year
        log.debug("Dynamic Config: 'blacklisted_max_year' set to Current Year (%s)", current_year)
    # -------------------------------------------------------------

    # --- UPDATED: Retrieve config filters but DON'T send to API ---
    config_countries = None
    if cfg.filters.movies.allowed_countries and 'ignore' not in cfg.filters.movies.allowed_countries:
        config_countries = cfg.filters.movies.allowed_countries

    config_languages = None
    if cfg.filters.movies.allowed_languages and 'ignore' not in cfg.filters.movies.allowed_languages:
        config_languages = cfg.filters.movies.allowed_languages

    # process genres
    if genres:
        # split comma separated list
        genres = sorted(genres.split(','), key=str.lower)

        # look for special keyword 'ignore'
        if 'ignore' in genres:
            # set special keyword 'ignore' to movies's blacklisted_genres list
            cfg['filters']['movies']['blacklisted_genres'] = ['ignore']
            # set genre search parameter to None
            genres = None
        else:
            # remove genre from movies's blacklisted_genres list, if it's there
            misc_helper.unblacklist_genres(genres, cfg['filters']['movies']['blacklisted_genres'])
            log.debug("Filter Trakt results with genre(s): %s", ', '.join(map(lambda x: x.title(), genres)))

    # process years parameter
    years, new_min_year, new_max_year = parameter_helper.years(
        years,
        cfg.filters.movies.blacklisted_min_year,
        cfg.filters.movies.blacklisted_max_year,
    )

    cfg['filters']['movies']['blacklisted_min_year'] = new_min_year
    cfg['filters']['movies']['blacklisted_max_year'] = new_max_year

    # runtimes range
    if cfg.filters.movies.blacklisted_min_runtime:
        min_runtime = cfg.filters.movies.blacklisted_min_runtime
    else:
        min_runtime = 0

    if cfg.filters.movies.blacklisted_max_runtime and cfg.filters.movies.blacklisted_max_runtime >= min_runtime:
        max_runtime = cfg.filters.movies.blacklisted_max_runtime
    else:
        max_runtime = 9999

    if min_runtime == 0 and max_runtime == 9999:
        runtimes = None
    else:
        runtimes = str(min_runtime) + '-' + str(max_runtime)

    # replace radarr root_folder if folder is supplied
    if folder:
        cfg['radarr']['root_folder'] = folder
    log.debug('Set root folder to: \'%s\'', cfg['radarr']['root_folder'])

    # replace radarr.minimum_availability if minimum_availability is supplied
    valid_min_avail = ['announced', 'in_cinemas', 'released']

    if minimum_availability:
        cfg['radarr']['minimum_availability'] = minimum_availability
    elif cfg['radarr']['minimum_availability'] not in valid_min_avail:
        cfg['radarr']['minimum_availability'] = 'released'

    log.debug('Set minimum availability to: \'%s\'', cfg['radarr']['minimum_availability'])

    # validate trakt api_key
    trakt = Trakt(cfg)
    radarr = Radarr(cfg.radarr.url, cfg.radarr.api_key)

    validate_trakt(trakt, notifications)
    validate_pvr(radarr, 'Radarr', notifications)

    # quality profile id
    quality_profile_id = get_quality_profile_id(radarr, cfg.radarr.quality)

    pvr_objects_list = get_objects(radarr, 'Radarr', notifications)
    pvr_exclusions_list = get_exclusions(radarr, 'Radarr')

    # get trakt movies list
    if list_type.lower() == 'anticipated':
        trakt_objects_list = trakt.get_anticipated_movies(
            years=years,
            countries=None,
            languages=None,
            genres=genres,
            runtimes=runtimes,
        )

    elif list_type.lower() == 'trending':
        trakt_objects_list = trakt.get_trending_movies(
            years=years,
            countries=None,
            languages=None,
            genres=genres,
            runtimes=runtimes,
        )

    elif list_type.lower() == 'popular':
        trakt_objects_list = trakt.get_popular_movies(
            years=years,
            countries=None,
            languages=None,
            genres=genres,
            runtimes=runtimes,
        )

    elif list_type.lower() == 'boxoffice':
        trakt_objects_list = trakt.get_boxoffice_movies()

    elif list_type.lower() == 'person':
        if not person:
            log.error("You must specify an person with the \'--person\' / \'-p\' parameter when using the \'person\'" +
                      " list type!")
            return None
        trakt_objects_list = trakt.get_person_movies(
            years=years,
            person=person,
            countries=None,
            languages=None,
            genres=genres,
            runtimes=runtimes,
            include_non_acting_roles=include_non_acting_roles,
        )

    elif list_type.lower() == 'recommended':
        trakt_objects_list = trakt.get_recommended_movies(
            authenticate_user,
            years=years,
            countries=None,
            languages=None,
            genres=genres,
            runtimes=runtimes,
        )

    elif list_type.lower().startswith('played'):
        most_type = misc_helper.substring_after(list_type.lower(), "_")
        trakt_objects_list = trakt.get_most_played_movies(
            years=years,
            countries=None,
            languages=None,
            genres=genres,
            runtimes=runtimes,
            most_type=most_type if most_type else None,
        )

    elif list_type.lower().startswith('watched'):
        most_type = misc_helper.substring_after(list_type.lower(), "_")
        trakt_objects_list = trakt.get_most_watched_movies(
            years=years,
            countries=None,
            languages=None,
            genres=genres,
            runtimes=runtimes,
            most_type=most_type if most_type else None,
        )

    elif list_type.lower() == 'watchlist':
        trakt_objects_list = trakt.get_watchlist_movies(authenticate_user)
    else:
        trakt_objects_list = trakt.get_user_list_movies(list_type, authenticate_user)

    if not trakt_objects_list:
        log.error("Aborting due to failure to retrieve Trakt \'%s\' movies list.", list_type.capitalize())
        if notifications:
            callback_notify(
                {'event': 'abort', 'type': 'movies', 'list_type': list_type,
                 'reason': 'Failure to retrieve Trakt \'%s\' movies list.' % list_type.capitalize()})
        return None
    else:
        log.info("Retrieved Trakt \'%s\' movies list, movies found: %d", list_type.capitalize(),
                 len(trakt_objects_list))

    # set remove_rejected_recommended to False if this is not the recommended list
    if list_type.lower() != 'recommended':
        remove_rejected_from_recommended = False

    # build filtered movie list without movies that exist in radarr
    processed_movies_list, removal_successful = radarr_helper.remove_existing_and_excluded_movies_from_trakt_list(
        pvr_objects_list,
        pvr_exclusions_list,
        trakt_objects_list,
        callback_remove_recommended if remove_rejected_from_recommended else None)

    if processed_movies_list is None:
        if not removal_successful:
            log.error("Aborting due to failure to remove existing Radarr movies from retrieved Trakt movies list.")
            if notifications:
                callback_notify({'event': 'abort', 'type': 'movies', 'list_type': list_type,
                                 'reason': 'Failure to remove existing Radarr movies from retrieved '
                                           'Trakt \'%s\' movies list.' % list_type.capitalize()})
        else:
            log.info("No more movies left to process in \'%s\' movies list.", list_type.capitalize())
        return None
    else:
        log.info("Removed existing and excluded Radarr movies from Trakt movies list. Movies left to process: %d",
                 len(processed_movies_list))

    # sort filtered movie list
    if sort == 'release':
        sorted_movies_list = misc_helper.sorted_list(processed_movies_list, 'movie', 'released')
        log.info("Sorted movies list to process by recent 'release' date.")
    elif sort == 'rating':
        sorted_movies_list = misc_helper.sorted_list(processed_movies_list, 'movie', 'rating')
        log.info("Sorted movies list to process by highest 'rating'.")
    else:
        sorted_movies_list = misc_helper.sorted_list(processed_movies_list, 'movie', 'votes')
        log.info("Sorted movies list to process by highest 'votes'.")

    # display specified min RT score
    if rotten_tomatoes is not None:
        if cfg.omdb.api_key:
            log.info("Minimum Rotten Tomatoes score of %d%% requested.", rotten_tomatoes)
        else:
            log.info("Skipping minimum Rotten Tomatoes score check as OMDb API Key is missing.")

    # loop movies
    log.info("Processing list now...")
    for sorted_movie in sorted_movies_list:
        # noinspection PyBroadException

        # set common series variables
        movie_data = sorted_movie.get('movie', {})
        movie_ids = movie_data.get('ids', {})

        movie_title = movie_data.get('title')
        movie_tmdb_id = movie_ids.get('tmdb')
        movie_imdb_id = movie_ids.get('imdb')

        if movie_tmdb_id is None or movie_imdb_id is None:
            continue


        # convert movie year to string
        year_data = sorted_movie['movie'].get('year')
        movie_year = str(year_data) if year_data else '????'

        # build list of genres
        genres_list = sorted_movie['movie'].get('genres', [])
        movie_genres = (', '.join(genres_list)).title() if genres_list else 'N/A'

        try:
            # --- LOCAL FILTERING (The "Anime Exception" Logic) ---
            is_anime = False
            if any('anime' in s.lower() for s in genres_list):
                 is_anime = True

            # 0. Check Genre Blacklist (MANUAL OVERRIDE to fix helper issue)
            # Applied to ALL content (Standard AND Anime) as per user request
            blacklisted_genres = cfg.filters.movies.get('blacklisted_genres', [])
            if blacklisted_genres:
                bad_genres = [g for g in genres_list if g.lower() in blacklisted_genres]
                if bad_genres:
                     log.info("SKIPPED: '%s' (Blacklisted Genre: %s)", movie_title, ', '.join(bad_genres))
                     continue

            # 1. Check Languages
            if config_languages:
                movie_lang = (sorted_movie['movie'].get('language') or '').lower()
                if movie_lang not in config_languages:
                    if not is_anime:
                        log.debug("SKIPPED: '%s' (Language '%s' not allowed)", movie_title, movie_lang)
                        continue
            
            # 2. Check Countries (Skip this local check - delegated to helper for Anime)
            if not is_anime and config_countries:
                movie_country = (sorted_movie['movie'].get('country') or '').lower()
                # Standard content must match allowed_countries
                if movie_country not in config_countries:
                     log.debug("SKIPPED: '%s' (Country '%s' not allowed)", movie_title, movie_country)
                     continue

            # 3. Check if genres matches genre(s) supplied via argument
            if genres and not misc_helper.allowed_genres(genres, 'movie', sorted_movie):
                log.debug("SKIPPING: \'%s (%s)\' because it was not from the genre(s): %s", movie_title,
                          movie_year, ', '.join(map(lambda x: x.title(), genres)))
                continue

            # 4. Check blacklist (With Configurable Anime Exception)
            
            # Create a clean copy of filters to modify for this specific check
            current_filters = cfg.filters.movies.copy()
            if is_anime:
                # --- SIMPLIFIED LOGIC ---
                # We simply force the allowed countries to be ['jp'].
                # The helper function will then reject anything that isn't 'jp'.
                current_filters['allowed_countries'] = ['jp']
                current_filters['allowed_languages'] = ['ja'] # Added to fix language blocking
                
                # Votes (STRICT SEPARATION: Only use Anime limit, or 0/Disable if not set)
                anime_votes = cfg.filters.movies.get('blacklisted_anime_min_votes')
                if anime_votes is not None and anime_votes != "":
                    current_filters['blacklisted_min_votes'] = int(anime_votes)
                else:
                    current_filters['blacklisted_min_votes'] = 0 # Explicitly disable
                
                # Rating (STRICT SEPARATION: Only use Anime limit, or 0.0/Disable if not set)
                anime_rating = cfg.filters.movies.get('blacklisted_anime_min_rating')
                if anime_rating is not None and anime_rating != "":
                    current_filters['blacklisted_min_rating'] = float(anime_rating)
                else:
                    current_filters['blacklisted_min_rating'] = 0.0 # Explicitly disable
            
            if trakt_helper.is_movie_blacklisted(
                    sorted_movie,
                    current_filters,  # PASS MODIFIED FILTERS
                    ignore_blacklist,
                    callback_remove_recommended if remove_rejected_from_recommended else None,
                    is_anime=is_anime
            ):
                log.info("SKIPPED: \'%s (%s)\'", movie_title, movie_year)
                continue

            # 5. Check if movie has a valid TMDb ID and that it exists on TMDb (Network Call)
            if not tmdb_helper.check_movie_tmdb_id(movie_title, movie_year, movie_tmdb_id):
                continue

            # 6. Skip movie if below user specified min RT score (Network Call)
            if rotten_tomatoes is not None and cfg.omdb.api_key:
                if not omdb_helper.does_movie_have_min_req_rt_score(
                        cfg.omdb.api_key,
                        movie_title,
                        movie_year,
                        movie_imdb_id,
                        rotten_tomatoes,
                ):
                    continue

            # 7. Proceed to Add
            log.info("ADDING: \'%s (%s)\' | Country: %s | Language: %s | Genre(s): %s ",
                     movie_title,
                     movie_year,
                     (sorted_movie['movie'].get('country', 'N/A') or 'N/A').upper(),
                     (sorted_movie['movie'].get('language', 'N/A') or 'N/A').upper(),
                     movie_genres,
                     )

            if dry_run:
                log.info("dry-run: SKIPPING")
            else:
                # add movie to radarr
                if radarr.add_movie(
                        sorted_movie['movie']['ids']['tmdb'],
                        movie_title,
                        movie_year,
                        sorted_movie['movie']['ids']['slug'],
                        quality_profile_id,
                        cfg.radarr.root_folder,
                        cfg.radarr.minimum_availability,
                        not no_search,
                ):

                    log.info("ADDED: \'%s (%s)\'", movie_title, movie_year)
                    
                    # -------------------------------------------------------------
                    # FEATURE: FETCH RT SCORE FOR RUN SUMMARY
                    # -------------------------------------------------------------
                    try:
                        if cfg.omdb.api_key and movie_imdb_id:
                            rt_url = "http://www.omdbapi.com/?apikey={}&i={}&tomatoes=true".format(cfg.omdb.api_key, movie_imdb_id)
                            rt_res = requests.get(rt_url, timeout=5)
                            if rt_res.status_code == 200:
                                rt_data = rt_res.json()
                                ratings = rt_data.get('Ratings', [])
                                for rating_item in ratings:
                                    if rating_item.get('Source') == 'Rotten Tomatoes':
                                        sorted_movie['movie']['rt_score'] = rating_item.get('Value')
                                        break
                    except Exception:
                        pass # Fail silently if OMDb fetch fails, summary just won't show it
                    # -------------------------------------------------------------

                    # Feature 5: Record Stats for Summary
                    sorted_movie['root_folder'] = cfg.radarr.root_folder
                    run_stats['movies'].append(sorted_movie)

                    if notifications:
                        callback_notify({'event': 'add_movie', 'list_type': list_type, 'movie': sorted_movie['movie']})
                    added_movies += 1
                else:
                    log.error("FAILED ADDING: \'%s (%s)\'", movie_title, movie_year)
                    continue

            # stop adding movies, if added_movies >= add_limit
            if add_limit and added_movies >= add_limit:
                break

            # sleep before adding any more
            time.sleep(add_delay)

        except Exception:
            log.exception("Exception while processing movie \'%s\': ", movie_title)

    log.info("Added %d new movie(s) to Radarr", added_movies)

    # send notification
    if notifications and (cfg.notifications.verbose or added_movies > 0):
        notify.send(message="Added %d movie(s) from Trakt's \'%s\' list" % (added_movies, list_type.capitalize()))

    return added_movies


############################################################
# CALLBACKS
############################################################


def callback_remove_recommended(media_type, media_info):
    from media.trakt import Trakt

    trakt = Trakt(cfg)

    if not media_info[media_type]['title'] or not media_info[media_type]['year']:
        log.debug("Skipping removing %s item from recommended list as no title/year was available:\n%s", media_type,
                  media_info)
        return

    # convert media year to string
    media_year = str(media_info[media_type]['year']) if media_info[media_type]['year'] else '????'

    media_name = '\'%s (%s)\'' % (media_info[media_type]['title'], media_year)

    if trakt.remove_recommended_item(media_type, media_info[media_type]['ids']['trakt']):
        log.info("Removed rejected recommended %s: \'%s\'", media_type, media_name)
    else:
        log.info("FAILED removing rejected recommended %s: \'%s\'", media_type, media_name)


def callback_notify(data):
    log.debug("Received callback data: %s", data)

    # handle event
    if data['event'] == 'add_movie':

        # convert movie year to string
        # Feature 1: Safe .get() included
        year_data = data['movie'].get('year')
        movie_year = str(year_data) if year_data else '????'

        if cfg.notifications.verbose:
            notify.send(
                message="Added \'%s\' movie: \'%s (%s)\'" % (data['list_type'].capitalize(), data['movie']['title'],
                                                             movie_year))
        return
    elif data['event'] == 'add_show':

        # convert series year to string
        # Feature 1: Safe .get() included
        year_data = data['show'].get('year')
        series_year = str(year_data) if year_data else '????'

        if cfg.notifications.verbose:
            notify.send(
                message="ADDED \'%s\' show: \'%s (%s)\'" % (data['list_type'].capitalize(), data['show']['title'],
                                                            series_year))
        return
    elif data['event'] == 'abort':
        notify.send(message="ABORTED ADDING Trakt \'%s\' %s due to: %s" % (data['list_type'].capitalize(), data['type'],
                                                                           data['reason']))
        return
    elif data['event'] == 'error':
        notify.send(message="Error: %s" % data['reason'])
        return
    else:
        log.error("Unexpected callback: %s", data)
    return


############################################################
# AUTOMATIC
############################################################

# Feature 5: Run Summary
def print_run_summary():
    global run_stats, cfg
    
    if run_stats['movies'] or run_stats['shows']:
        log.info("############################################################")
        log.info("# RUN SUMMARY")
        log.info("############################################################")
        
        # --- MOVIES SUMMARY ---
        if run_stats['movies']:
            log.info("Movies Added (%d):", len(run_stats['movies']))
            for item in run_stats['movies']:
                # Safe Extraction
                movie = item.get('movie', {})
                title = movie.get('title', 'Unknown')
                year = movie.get('year') or '????'
                dest_folder = item.get('root_folder', 'N/A')
                
                # Standard Info (Always shown)
                log.info("   > %s (%s)", title, year)
                
                # Detailed Auditing Data (DEBUG ONLY)
                if cfg.core.debug:
                    log.info("        Destination: %s", dest_folder)
                    
                    country = (movie.get('country') or 'us').upper()
                    language = (movie.get('language') or 'en').upper()
                    genres = ", ".join(movie.get('genres', []))
                    rating = movie.get('rating', 0.0)
                    votes = movie.get('votes', 0)
                    runtime = movie.get('runtime', 0)
                    certification = movie.get('certification', 'N/A')
                    rt_score = movie.get('rt_score', 'N/A') # Populated by fetch logic

                    log.info("        Genre:         %s", genres)
                    log.info("        Rating:        %.1f (%s votes) | RT: %s", rating, "{:,}".format(votes), rt_score)
                    log.info("        Language:      %s", language)
                    log.info("        Country:       %s", country)
                    log.info("        Runtime:       %sm", runtime)
                    log.info("        Certification: %s", certification)
                    log.info("") # Empty line for spacing in debug mode

        # --- SHOWS SUMMARY ---
        if run_stats['shows']:
            log.info("Shows Added (%d):", len(run_stats['shows']))
            for item in run_stats['shows']:
                # Safe Extraction
                show = item.get('show', {})
                title = show.get('title', 'Unknown')
                year = show.get('year') or '????'
                dest_folder = item.get('root_folder', 'N/A')
                
                # Standard Info (Always shown)
                log.info("   > %s (%s)", title, year)
                
                # Detailed Auditing Data (DEBUG ONLY)
                if cfg.core.debug:
                    log.info("        Destination: %s", dest_folder)

                    country = (show.get('country') or 'us').upper()
                    language = (show.get('language') or 'en').upper()
                    genres = ", ".join(show.get('genres', []))
                    rating = show.get('rating', 0.0)
                    votes = show.get('votes', 0)
                    runtime = show.get('runtime', 0)
                    certification = show.get('certification', 'N/A')
                    network = (show.get('network') or 'N/A').upper()

                    log.info("        Genre:         %s", genres)
                    log.info("        Rating:        %.1f (%s votes)", rating, "{:,}".format(votes))
                    log.info("        Network:       %s", network)
                    log.info("        Language:      %s", language)
                    log.info("        Country:       %s", country)
                    log.info("        Runtime:       %sm", runtime)
                    log.info("        Certification: %s", certification)
                    log.info("") # Empty line for spacing in debug mode
                
        log.info("############################################################")
        log.info("")
        
        # Reset stats for next run
        run_stats['movies'] = []
        run_stats['shows'] = []

def automatic_shows(
        add_delay=2.5,
        sort='votes',
        no_search=False,
        notifications=False,
        ignore_blacklist=False,
):

    from media.trakt import Trakt

    # REMOVED: reset_log_file() (Feature 6 excluded)

    total_shows_added = 0
    # noinspection PyBroadException
    try:
        log.info("Automatic Shows task started.")

        # send notification
        if notifications and cfg.notifications.verbose:
            notify.send(message="Automatic Shows task started.")

        for list_type, value in cfg.automatic.shows.items():
            added_shows = None

            if list_type.lower() == 'interval':
                continue

            if list_type.lower() in Trakt.non_user_lists or (
                    '_' in list_type and list_type.lower().partition("_")[0] in Trakt.non_user_lists):
                limit = value

                if limit <= 0:
                    log.info("SKIPPED Trakt's \'%s\' shows list.", list_type.capitalize())
                    continue
                else:
                    log.info("ADDING %d show(s) from Trakt's \'%s\' list.", limit, list_type.capitalize())

                local_ignore_blacklist = ignore_blacklist

                if list_type.lower() in cfg.filters.shows.disabled_for:
                    local_ignore_blacklist = True

                # run shows
                added_shows = shows.callback(
                    list_type=list_type,
                    add_limit=limit,
                    add_delay=add_delay,
                    sort=sort,
                    no_search=no_search,
                    notifications=notifications,
                    ignore_blacklist=local_ignore_blacklist,
                )

            elif list_type.lower() == 'watchlist':
                for authenticate_user, limit in value.items():
                    if limit <= 0:
                        log.info("SKIPPED Trakt user \'%s\''s \'%s\'", authenticate_user, list_type.capitalize)
                        continue
                    else:
                        log.info("ADDING %d show(s) from Trakt user \'%s\''s \'%s\'", limit, authenticate_user,
                                 list_type.capitalize)

                    local_ignore_blacklist = ignore_blacklist

                    if "watchlist:%s".format(authenticate_user) in cfg.filters.shows.disabled_for:
                        local_ignore_blacklist = True

                    # run shows
                    added_shows = shows.callback(
                        list_type=list_type,
                        add_limit=limit,
                        add_delay=add_delay,
                        sort=sort,
                        no_search=no_search,
                        notifications=notifications,
                        authenticate_user=authenticate_user,
                        ignore_blacklist=local_ignore_blacklist,
                        # ...
                    )

            elif list_type.lower() == 'lists':

                if len(value.items()) == 0:
                    log.info("SKIPPED Trakt's \'%s\' shows list.", list_type.capitalize())
                    continue

                for list_, v in value.items():
                    if isinstance(v, dict):
                        authenticate_user = v['authenticate_user']
                        limit = v['limit']
                    else:
                        authenticate_user = None
                        limit = v

                    if limit <= 0:
                        log.info("SKIPPED Trakt's \'%s\' shows list.", list_)
                        continue

                    local_ignore_blacklist = ignore_blacklist

                    if "list:%s".format(list_) in cfg.filters.shows.disabled_for:
                        local_ignore_blacklist = True

                    # run shows
                    added_shows = shows.callback(
                        list_type=list_,
                        add_limit=limit,
                        add_delay=add_delay,
                        sort=sort,
                        no_search=no_search,
                        notifications=notifications,
                        authenticate_user=authenticate_user,
                        ignore_blacklist=local_ignore_blacklist,
                    )

            if added_shows is None:
                if list_type.lower() != 'lists':
                    log.info("FAILED ADDING shows from Trakt's \'%s\' list.", list_type.capitalize())
                time.sleep(10)
                continue
            total_shows_added += added_shows

            # sleep
            time.sleep(10)

        log.info("FINISHED: Added %d show(s) total to Sonarr!", total_shows_added)
        # send notification
        if notifications and (cfg.notifications.verbose or total_shows_added > 0):
            notify.send(message="Added %d show(s) total to Sonarr!" % total_shows_added)

    except Exception:
        log.exception("Exception while automatically adding shows: ")
    return


def automatic_movies(
        add_delay=2.5,
        sort='votes',
        no_search=False,
        notifications=False,
        ignore_blacklist=False,
        rotten_tomatoes=None,
):

    from media.trakt import Trakt

    # REMOVED: reset_log_file() (Feature 6 excluded)

    total_movies_added = 0
    # noinspection PyBroadException
    try:
        log.info("Automatic Movies task started.")

        # send notification
        if notifications and cfg.notifications.verbose:
            notify.send(message="Automatic Movies task started.")

        for list_type, value in cfg.automatic.movies.items():
            added_movies = None

            if list_type.lower() == 'interval':
                continue

            if list_type.lower() in Trakt.non_user_lists or (
                    '_' in list_type and list_type.lower().partition("_")[0] in Trakt.non_user_lists):
                limit = value

                if limit <= 0:
                    log.info("SKIPPED Trakt's \'%s\' movies list.", list_type.capitalize())
                    continue
                else:
                    log.info("ADDING %d movie(s) from Trakt's \'%s\' list.", limit, list_type.capitalize())

                local_ignore_blacklist = ignore_blacklist

                if list_type.lower() in cfg.filters.movies.disabled_for:
                    local_ignore_blacklist = True

                # run movies
                added_movies = movies.callback(
                    list_type=list_type,
                    add_limit=limit,
                    add_delay=add_delay,
                    sort=sort,
                    no_search=no_search,
                    notifications=notifications,
                    ignore_blacklist=local_ignore_blacklist,
                    rotten_tomatoes=rotten_tomatoes,
                )

            elif list_type.lower() == 'watchlist':
                for authenticate_user, limit in value.items():
                    if limit <= 0:
                        log.info("SKIPPED Trakt user \'%s\''s \'%s\'", authenticate_user, list_type.capitalize)
                        continue
                    else:
                        log.info("ADDING %d movie(s) from Trakt user \'%s\''s \'%s\'", limit,
                                 authenticate_user, list_type.capitalize())

                    local_ignore_blacklist = ignore_blacklist

                    if "watchlist:%s".format(authenticate_user) in cfg.filters.movies.disabled_for:
                        local_ignore_blacklist = True

                    # run movies
                    added_movies = movies.callback(
                        list_type=list_type,
                        add_limit=limit,
                        add_delay=add_delay,
                        sort=sort,
                        no_search=no_search,
                        notifications=notifications,
                        authenticate_user=authenticate_user,
                        ignore_blacklist=local_ignore_blacklist,
                        rotten_tomatoes=rotten_tomatoes,
                    )

            elif list_type.lower() == 'lists':

                if len(value.items()) == 0:
                    log.info("SKIPPED Trakt's \'%s\' movies list", list_type.capitalize())
                    continue

                for list_, v in value.items():
                    if isinstance(v, dict):
                        authenticate_user = v['authenticate_user']
                        limit = v['limit']
                    else:
                        authenticate_user = None
                        limit = v

                    if limit <= 0:
                        log.info("SKIPPED Trakt's \'%s\' movies list.", list_)
                        continue

                    local_ignore_blacklist = ignore_blacklist

                    if "list:%s".format(list_) in cfg.filters.movies.disabled_for:
                        local_ignore_blacklist = True

                    # run shows
                    added_movies = movies.callback(
                        list_type=list_,
                        add_limit=limit,
                        add_delay=add_delay,
                        sort=sort,
                        no_search=no_search,
                        notifications=notifications,
                        authenticate_user=authenticate_user,
                        ignore_blacklist=local_ignore_blacklist,
                        rotten_tomatoes=rotten_tomatoes,
                    )

            if added_movies is None:
                if list_type.lower() != 'lists':
                    log.info("FAILED ADDING movies from Trakt's \'%s\' list.", list_type.capitalize())
                time.sleep(10)
                continue
            total_movies_added += added_movies

            # sleep
            time.sleep(10)

        log.info("FINISHED: Added %d movie(s) total to Radarr!", total_movies_added)
        # send notification
        if notifications and (cfg.notifications.verbose or total_movies_added > 0):
            notify.send(message="Added %d movie(s) total to Radarr!" % total_movies_added)

    except Exception:
        log.exception("Exception while automatically adding movies: ")
    return


@app.command(help='Run Traktarr in automatic mode.')
@click.option(
    '--add-delay', '-d',
    default=2.5,
    help='Seconds between each add request to Sonarr / Radarr.',
    show_default=True)
@click.option(
    '--sort', '-s',
    default='votes',
    type=click.Choice(['votes', 'rating', 'release']),
    help='Sort list to process.',
    show_default=True)
@click.option(
    '--no-search',
    is_flag=True,
    help='Disable search when adding to Sonarr / Radarr.')
@click.option(
    '--run-now',
    is_flag=True,
    help="Do a first run immediately without waiting.")
@click.option(
    '--no-notifications',
    is_flag=True,
    help="Disable notifications.")
@click.option(
    '--ignore-blacklist',
    is_flag=True,
    help='Ignores the blacklist when running the command.')
def run(
        add_delay=2.5,
        sort='votes',
        no_search=False,
        run_now=False,
        no_notifications=False,
        ignore_blacklist=False,
):

    log.info("Automatic mode is now running.")

    # REMOVED: reset_log_file() (Feature 6 excluded)

    # send notification
    if not no_notifications and cfg.notifications.verbose:
        notify.send(message="Automatic mode is now running.")

    # Add tasks to schedule and do first run if enabled
    if cfg.automatic.movies.interval and cfg.automatic.movies.interval > 0:
        movie_schedule = schedule.every(cfg.automatic.movies.interval).hours.do(
            automatic_movies,
            add_delay,
            sort,
            no_search,
            not no_notifications,
            ignore_blacklist,
            int(cfg.filters.movies.rotten_tomatoes) if cfg.filters.movies.rotten_tomatoes != "" else None,
        )
        if run_now:
            movie_schedule.run()

            # Sleep between tasks
            time.sleep(add_delay)

    if cfg.automatic.shows.interval and cfg.automatic.shows.interval > 0:
        shows_schedule = schedule.every(cfg.automatic.shows.interval).hours.do(
            automatic_shows,
            add_delay,
            sort,
            no_search,
            not no_notifications,
            ignore_blacklist
        )
        if run_now:
            shows_schedule.run()

            # Sleep between tasks
            time.sleep(add_delay)
    
    # Feature 5: Print summary after immediate run
    print_run_summary()

    # Enter running schedule
    while True:
        try:
            # Sleep until next run
            log.info("Next job at %s", schedule.next_run())
            time.sleep(max(schedule.idle_seconds(), 0))
            # Check jobs to run
            schedule.run_pending()
            
            # Feature 5: Print summary after scheduled runs
            print_run_summary()

        except Exception as e:
            log.exception("Unhandled exception occurred while processing scheduled tasks: %s", e)
            time.sleep(1)


############################################################
# MISC
############################################################

def init_notifications():
    # noinspection PyBroadException
    try:
        for notification_name, notification_config in cfg.notifications.items():
            if notification_name.lower() == 'verbose':
                continue

            notify.load(**notification_config)
    except Exception:
        log.exception("Exception initializing notification agents: ")
    return


# Handles exit signals, cancels jobs and exits cleanly
# noinspection PyUnusedLocal
def exit_handler(signum, frame):
    log.info("Received %s, canceling jobs and exiting.", signal.Signals(signum).name)
    schedule.clear()
    exit()


############################################################
# MAIN
############################################################

if __name__ == "__main__":
    print("")

    f = Figlet(font='graffiti')
    print(f.renderText('Traktarr'))

    print("""
#########################################################################
# Author:   l3uddz                                                      #
# URL:      https://github.com/l3uddz/traktarr                          #
# --                                                                    #
#         Part of the Cloudbox project: https://cloudbox.works          #
#########################################################################
#                   GNU General Public License v3.0                     #
#########################################################################
""")

    # Register the signal handlers
    signal.signal(signal.SIGTERM, exit_handler)
    signal.signal(signal.SIGINT, exit_handler)

    # Start application
    app()
