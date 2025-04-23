import streamlit as st
import pandas as pd
import requests
from transformers import pipeline
from datetime import datetime, timedelta
import isodate

# --- API KEYS ---
YOUTUBE_API_KEY = st.secrets["GOOGLE_API_KEY"]

# --- NLP Pipeline ---
sentiment_pipeline = pipeline("sentiment-analysis")

# --- Helper: Analyze Sentiment ---
def analyze_sentiment(text):
    try:
        result = sentiment_pipeline(text[:512])[0]
        return result['label'], round(result['score'], 3)
    except:
        return "NEUTRAL", 0.5

# --- YouTube API Fetch ---
def fetch_youtube_videos(query, days=7, max_results=50, duration_filter=['any'], language='en'):
    published_after = (datetime.utcnow() - timedelta(days=days)).isoformat("T") + "Z"
    search_url = f"https://www.googleapis.com/youtube/v3/search"
    all_items = []
    next_page_token = None

    while len(all_items) < max_results:
        search_params = {
            'part': 'snippet',
            'q': query,
            'type': 'video',
            'maxResults': min(50, max_results - len(all_items)),
            'publishedAfter': published_after,
            'key': YOUTUBE_API_KEY,
            'videoDuration': duration_filter[0] if len(duration_filter) == 1 else 'any',
            'relevanceLanguage': language,
            'order': 'date'
        }
        if next_page_token:
            search_params['pageToken'] = next_page_token

        search_response = requests.get(search_url, params=search_params).json()
        if "error" in search_response:
            st.error(f"Search API Error: {search_response['error']['message']}")
            return []

        items = search_response.get("items", [])
        all_items.extend(items)
        next_page_token = search_response.get("nextPageToken")
        if not next_page_token:
            break

    if "error" in search_response:
        st.error(f"Search API Error: {search_response['error']['message']}")
        return []

    items = []
    video_ids = [item['id']['videoId'] for item in all_items]
    st.write(f"Fetched {len(video_ids)} videos from search API (paginated)")

    # Fetch view counts and duration
    if video_ids:
        videos_url = "https://www.googleapis.com/youtube/v3/videos"
        items = []
        for i in range(0, len(video_ids), 50):
            batch_ids = video_ids[i:i+50]
            videos_params = {
                'part': 'statistics,snippet,contentDetails',
                'id': ','.join(batch_ids),
                'key': YOUTUBE_API_KEY
            }
            video_response = requests.get(videos_url, params=videos_params).json()

            if "error" in video_response:
                st.error(f"Video details API Error: {video_response['error']['message']}")
                continue

        if "error" in video_response:
            st.error(f"Video details API Error: {video_response['error']['message']}")
            return []

        for i, item in enumerate(video_response.get("items", [])):
            if 'contentDetails' not in item or 'duration' not in item['contentDetails']:
                continue
            title = item['snippet']['title']
            description = item['snippet'].get('description', '')
            published = item['snippet']['publishedAt']
            link = f"https://www.youtube.com/watch?v={item['id']}"
            views = int(item['statistics'].get('viewCount', 0))
            duration_str = item['contentDetails']['duration']
            duration = isodate.parse_duration(duration_str).total_seconds()
            sentiment, score = analyze_sentiment(title + " " + description)
            items.append({
                'Title': title,
                'Published': published,
                'Link': link,
                'VideoId': item['id'],
                'Views': views,
                'Sentiment': sentiment,
                'Score': score,
                'Description': description,
                'DurationSeconds': duration
            })
            st.session_state.progress_youtube.progress((i + 1) / len(video_response.get("items", [])))
    return items

# --- Library Setup ---
from io import StringIO
import os
LIBRARY_PATH = "video_library.csv"
if os.path.exists(LIBRARY_PATH):
    video_library = pd.read_csv(LIBRARY_PATH)
    if 'Favorite' not in video_library.columns:
        video_library['Favorite'] = False
else:
    video_library = pd.DataFrame(columns=["VideoId"])

# --- Streamlit UI ---
with st.sidebar:
    st.header("📚 Video Library Browser")
    if not video_library.empty:
        sort_option = st.selectbox("Sort by", options=["Views", "Published", "Sentiment"])
        if sort_option == "Views":
            library_display = video_library.sort_values(by="Views", ascending=False)
        elif sort_option == "Published":
            library_display = video_library.sort_values(by="Published", ascending=False)
        else:
            library_display = video_library.sort_values(by="Sentiment")

        preview_count = st.slider("Number of results to preview", 1, min(25, len(library_display)), 5)
        st.write("Recent videos from your library:")
        for i, row in library_display.head(preview_count).iterrows():
            is_fav = row.get("Favorite", False)
            fav_toggle = st.checkbox("⭐", value=is_fav, key=f"fav_{i}")
            video_library.at[row.name, "Favorite"] = fav_toggle
            st.markdown(f"🔗 [{row['Title']}]({row['Link']}) - {row['Views']:,} views")
        video_library.to_csv(LIBRARY_PATH, index=False)
    else:
        st.info("Your video library is empty. Run a search to start populating it.")
st.title("🐷 Truffle FUD")
query = st.text_input("Search Query", "electric vehicle")
days = st.slider("Lookback Period (days)", 1, 30, 7)
min_views = st.number_input("Minimum View Count", value=10000, step=1000)
max_results = st.slider("How many videos to fetch (max 500)", 10, 500, 100, step=10)
filter_negative = st.checkbox("Only show videos with negative sentiment", value=True)
video_duration = [st.selectbox("Select Video Duration", options=["any", "short", "medium", "long"], index=2)]
english_only = st.checkbox("English Only", value=True)
language = "en" if english_only else "any"

if st.button("Run Analysis"):
    st.session_state.progress_youtube = st.progress(0, text="Fetching and analyzing YouTube videos...")
    yt_data = fetch_youtube_videos(query, days, max_results=max_results, duration_filter=video_duration, language=language)
    new_videos = [item for item in yt_data if item['VideoId'] not in video_library['VideoId'].values]
    st.session_state.progress_youtube.empty()

    st.write(f"Videos fetched before filtering: {len(yt_data)}")
    st.write(f"Videos not previously logged: {len(new_videos)}")

    filtered_data = [item for item in new_videos if item['Views'] >= min_views]
    st.write(f"Videos after applying view filter (>{min_views} views): {len(filtered_data)}")

    if filter_negative:
        filtered_data = [item for item in filtered_data if item['Sentiment'] == "NEGATIVE"]
        st.write(f"Videos after filtering for negative sentiment: {len(filtered_data)}")

    filtered_data = sorted(filtered_data, key=lambda x: x['Views'], reverse=True)

    if not filtered_data:
        st.warning("No new videos found. Showing previous results from the library.")
        filtered_data = video_library.to_dict(orient='records')
        filtered_data = sorted(filtered_data, key=lambda x: x['Views'], reverse=True)
    else:
        st.success("Done!")
        new_entries_df = pd.DataFrame(filtered_data)
        new_entries_df['Favorite'] = False
        video_library = pd.concat([video_library, new_entries_df], ignore_index=True)
        video_library.to_csv(LIBRARY_PATH, index=False)
        for video in filtered_data:
            col1, col2 = st.columns([3, 5])
            with col1:
                st.image(f"https://img.youtube.com/vi/{video['VideoId']}/hqdefault.jpg", use_container_width=True)
            with col2:
                st.markdown(f"<div style='padding-bottom: 0.5rem;'><a href='{video['Link']}' target='_blank' style='text-decoration: none; color: white; font-size: 1.1rem; font-weight: bold;'>{video['Title']}</a></div>", unsafe_allow_html=True)
                st.markdown(f"<span style='font-size: 0.9rem; color: gray;'>{video['Views']:,} views • {int(video['DurationSeconds']//60)} min {int(video['DurationSeconds']%60)} sec • {video['Published'][:10]}</span>", unsafe_allow_html=True)
                st.markdown(f"<span style='font-size: 0.85rem;'>Sentiment: <strong>{video['Sentiment']}</strong> (Score: {video['Score']})</span>", unsafe_allow_html=True)
                st.markdown(f"<p style='margin-top: 0.5rem;'>{video['Description'][:200]}{'...' if len(video['Description']) > 200 else ''}</p>", unsafe_allow_html=True)
            st.markdown("<hr style='margin: 1rem 0;'>", unsafe_allow_html=True)
