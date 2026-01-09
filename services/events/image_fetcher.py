import requests
import os
from typing import Optional, Tuple  

TMDB_API_KEY = os.getenv("TMDB_API_KEY", "")
LASTFM_API_KEY = os.getenv("LASTFM_API_KEY", "")
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "")

def fetch_movie_poster(movie_name: str) -> Optional[str]:
    """Fetch movie poster from TMDB API"""
    if not TMDB_API_KEY:
        print("[WARNING] TMDB_API_KEY not set, using placeholder")
        return f"https://via.placeholder.com/500x750/667eea/ffffff?text={movie_name.replace(' ', '+')}"
    
    try:
        search_url = f"https://api.themoviedb.org/3/search/movie"
        params = {
            "api_key": TMDB_API_KEY,
            "query": movie_name
        }
        
        response = requests.get(search_url, params=params, timeout=5)
        data = response.json()
        
        if data.get("results") and len(data["results"]) > 0:
            poster_path = data["results"][0].get("poster_path")
            if poster_path:
                print(f"[INFO] Found TMDB poster for: {movie_name}")
                return f"https://image.tmdb.org/t/p/w500{poster_path}"
        
        print(f"[INFO] No poster found for movie: {movie_name}")
        return f"https://via.placeholder.com/500x750/667eea/ffffff?text={movie_name.replace(' ', '+')}"
    
    except Exception as e:
        print(f"[ERROR] Failed to fetch movie poster: {e}")
        return f"https://via.placeholder.com/500x750/667eea/ffffff?text={movie_name.replace(' ', '+')}"

def fetch_artist_image_lastfm(artist_name: str) -> Optional[str]:
    """Fetch artist image from Last.fm API"""
    clean_name = artist_name.split(" Live")[0].split(" World")[0].split(" Tour")[0].split(" -")[0].strip()
    
    if not LASTFM_API_KEY:
        print("[WARNING] LASTFM_API_KEY not set, using placeholder")
        return f"https://via.placeholder.com/500x500/764ba2/ffffff?text={clean_name.replace(' ', '+')}"
    
    try:
        url = "http://ws.audioscrobbler.com/2.0/"
        params = {
            "method": "artist.getinfo",
            "artist": clean_name,
            "api_key": LASTFM_API_KEY,
            "format": "json"
        }
        
        response = requests.get(url, params=params, timeout=5)
        data = response.json()
        
        if "artist" in data and "image" in data["artist"]:
            images = data["artist"]["image"]
            # Get largest image (usually "extralarge" or "mega")
            for img in reversed(images):
                if img.get("#text") and img.get("#text") != "":
                    print(f"[INFO] Found Last.fm image for: {clean_name}")
                    return img["#text"]
        
        print(f"[INFO] No image found for artist: {clean_name}")
        return f"https://via.placeholder.com/500x500/764ba2/ffffff?text={clean_name.replace(' ', '+')}"
    
    except Exception as e:
        print(f"[ERROR] Last.fm API error: {e}")
        return f"https://via.placeholder.com/500x500/764ba2/ffffff?text={clean_name.replace(' ', '+')}"
    
def fetch_artist_image_deezer(artist_name: str) -> Optional[str]:
    """Fetch artist image from Deezer API (no API key needed!)"""
    clean_name = artist_name.split(" Live")[0].split(" World")[0].split(" Tour")[0].split(" -")[0].strip()
    
    try:
        url = "https://api.deezer.com/search/artist"
        params = {
            "q": clean_name,
            "limit": 1
        }
        
        response = requests.get(url, params=params, timeout=5)
        data = response.json()
        
        if data.get("data") and len(data["data"]) > 0:
            artist = data["data"][0]
            # Use picture_big (500x500) for good quality
            if artist.get("picture_big"):
                print(f"[INFO] Found Deezer image for: {clean_name}")
                return artist["picture_big"]
        
        print(f"[INFO] No Deezer image found for: {clean_name}")
        return f"https://via.placeholder.com/500x500/764ba2/ffffff?text={clean_name.replace(' ', '+')}"
    
    except Exception as e:
        print(f"[ERROR] Deezer API error: {e}")
        return f"https://via.placeholder.com/500x500/764ba2/ffffff?text={clean_name.replace(' ', '+')}"

def get_spotify_token() -> Optional[str]:
    """Get Spotify access token"""
    if not SPOTIFY_CLIENT_ID or not SPOTIFY_CLIENT_SECRET:
        return None
    
    try:
        auth_url = "https://accounts.spotify.com/api/token"
        auth_response = requests.post(auth_url, {
            "grant_type": "client_credentials",
            "client_id": SPOTIFY_CLIENT_ID,
            "client_secret": SPOTIFY_CLIENT_SECRET
        }, timeout=5)
        
        auth_data = auth_response.json()
        return auth_data.get("access_token")
    except Exception as e:
        print(f"[ERROR] Failed to get Spotify token: {e}")
        return None

def fetch_artist_image_spotify(artist_name: str) -> Optional[str]:
    """Fetch artist image from Spotify API"""
    clean_name = artist_name.split(" Live")[0].split(" World")[0].split(" Tour")[0].split(" -")[0].strip()
    
    token = get_spotify_token()
    
    if not token:
        return None
    
    try:
        search_url = "https://api.spotify.com/v1/search"
        headers = {"Authorization": f"Bearer {token}"}
        params = {
            "q": clean_name,
            "type": "artist",
            "limit": 1
        }
        
        response = requests.get(search_url, headers=headers, params=params, timeout=5)
        data = response.json()
        
        if data.get("artists") and data["artists"].get("items"):
            artist = data["artists"]["items"][0]
            images = artist.get("images", [])
            if images:
                print(f"[INFO] Found Spotify image for: {clean_name}")
                return images[0]["url"]
        
        return None
    
    except Exception as e:
        print(f"[ERROR] Failed to fetch Spotify image: {e}")
        return None

def fetch_artist_image(artist_name: str) -> Optional[str]:
    """
    Fetch artist image - tries Deezer first, then Last.fm as fallback
    """
    # Try Deezer first (no API key needed!)
    image_url = fetch_artist_image_deezer(artist_name)
    
    # If Deezer returns placeholder, try Last.fm
    if "placeholder" in image_url and LASTFM_API_KEY:
        lastfm_url = fetch_artist_image_lastfm(artist_name)
        if "placeholder" not in lastfm_url:
            return lastfm_url
    
    return image_url

def detect_event_type(event_name: str) -> str:
    """Detect if event is a movie or concert based on name"""
    concert_keywords = ["concert", "live", "tour", "festival", "show"]
    name_lower = event_name.lower()
    
    for keyword in concert_keywords:
        if keyword in name_lower:
            return "concert"
    
    return "movie"

def fetch_event_image(event_name: str, event_type: str = None) -> Tuple[Optional[str], str]:
    """
    Fetch appropriate image based on event type.
    Returns (image_url, detected_event_type)
    """
    if not event_type:
        event_type = detect_event_type(event_name)
    
    if event_type == "concert":
        image_url = fetch_artist_image(event_name)
    else:
        image_url = fetch_movie_poster(event_name)
    
    return image_url, event_type