import os
import requests
import pandas as pd
import streamlit as st
from datetime import datetime, date

# --- Page config ---
st.set_page_config(page_title="FUD Finder", layout="wide")

# --- Responsive & constrained width styling ---
st.markdown(
    """
    <style>
    /* Mobile-friendly padding */
    .reportview-container .main .block-container {
        padding: 1rem;
    }
    /* Constrain max width on larger screens */
    @media (min-width: 768px) {
        .reportview-container .main .block-container {
            max-width: 800px;
            margin: auto;
        }
    }
    </style>
    """,
    unsafe_allow_html=True
)

# --- Load secrets ---
# .streamlit/secrets.toml should contain:
# GOOGLE_API_KEY = "YOUR_API_KEY"
API_KEY = st.secrets['GOOGLE_API_KEY']
BASE_URL = "https://factchecktools.googleapis.com/v1alpha1/claims:search"

@st.cache_data(show_spinner=False)
def fetch_factchecks(query: str):
    """
    Fetch all fact-check reviews for a given query and return flattened list.
    """
    all_rows = []
    page_token = None
    language = 'en'

    while True:
        params = {
            'query': query,
            'languageCode': language,
            'pageSize': 100,
            'key': API_KEY
        }
        if page_token:
            params['pageToken'] = page_token

        resp = requests.get(BASE_URL, params=params)
        resp.raise_for_status()
        data = resp.json()

        for claim in data.get('claims', []):
            base = {
                'claimText': claim.get('text'),
                'claimant': claim.get('claimant'),
                'claimDate': claim.get('claimDate')
            }
            for review in claim.get('claimReview', []):
                if not review.get('languageCode', '').startswith(language):
                    continue
                pub = review.get('publisher') or {}
                # extract publisher logo if available
                logo = pub.get('logo', {})
                all_rows.append({
                    **base,
                    'publisher': pub.get('name'),
                    'site': pub.get('site'),
                    'reviewUrl': review.get('url'),
                    'reviewTitle': review.get('title') or review.get('url'),
                    'reviewDate': review.get('reviewDate'),
                    'textualRating': review.get('textualRating'),
                    'logoUrl': logo.get('url')
                })
        page_token = data.get('nextPageToken')
        if not page_token:
            break
    return all_rows

# --- UI ---
st.title("FUD Finder")

# Search bar
query = st.text_input("Search query", "Electric vehicle")

# Date filters and sort option
today = date.today()
col1, col2, col3 = st.columns([2,2,2])
with col1:
    start = st.date_input("Start date", today.replace(year=today.year-1))
with col2:
    end = st.date_input("End date", today)
with col3:
    sort_opt = st.selectbox("Sort by", ["Most reviews", "Newest first", "Oldest first"])

if st.button("Search"):
    with st.spinner("Fetching results..."):
        rows = fetch_factchecks(query)
        df = pd.DataFrame(rows)

        # parse dates as UTC-aware
        df['reviewDate'] = pd.to_datetime(df['reviewDate'], errors='coerce', utc=True)
        df['claimDate'] = pd.to_datetime(df['claimDate'], errors='coerce', utc=True)

        # filter by original article publish date
        start_ts = pd.Timestamp(start).tz_localize('UTC')
        end_ts = pd.Timestamp(end).tz_localize('UTC')
        df = df[(df['claimDate'] >= start_ts) & (df['claimDate'] <= end_ts)]

        # remove exact duplicate reviews
        df = df.drop_duplicates(subset=['reviewUrl'])

        # compute weight = count of duplicates per title
        df['weight'] = df.groupby('reviewTitle')['reviewTitle'].transform('count')

        # keep only one row per title (preferring newest fact-check)
        df = df.sort_values(['weight', 'reviewDate'], ascending=[False, False])
        df = df.drop_duplicates(subset=['reviewTitle'], keep='first')

        # sort by selected option
        if sort_opt == "Most reviews":
            df = df.sort_values(by=['weight', 'claimDate'], ascending=[False, False])
        elif sort_opt == "Newest first":
            df = df.sort_values(by='claimDate', ascending=False)
        else:
            df = df.sort_values(by='claimDate', ascending=True)

        st.markdown(f"**Found {len(df)} unique results ({df['weight'].sum()} total reviews)**")

        # Display results in cards
        for _, row in df.iterrows():
            cols = st.columns([1, 4], gap="small")
            # publisher logo
            if row.get('logoUrl'):
                cols[0].image(row['logoUrl'], width=64)
            # content
            title = f"{row['reviewTitle']} ({row['weight']} reviews)" if row['weight'] > 1 else row['reviewTitle']
            cols[1].markdown(f"#### [{title}]({row['reviewUrl']})")
            meta = [row['publisher']] if row['publisher'] else []
            meta.append(row['claimDate'].strftime('%Y-%m-%d'))
            if not pd.isna(row['reviewDate']):
                meta.append(f"Fact-checked: {row['reviewDate'].strftime('%Y-%m-%d')}")
            if row['textualRating']:
                meta.append(row['textualRating'])
            cols[1].markdown(" • ".join(meta))
            if row['claimText']:
                cols[1].write(row['claimText'])
            st.divider()

        # CSV download
        csv_data = df.to_csv(index=False)
        st.download_button(
            label="Download results as CSV",
            data=csv_data,
            file_name=f"factchecks_{datetime.now().strftime('%Y-%m-%d-%H-%M-%S')}.csv",
            mime='text/csv'
        )
