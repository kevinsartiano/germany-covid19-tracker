"""Germany Covid-19 Tracker."""

import csv
import json
import os
from operator import itemgetter

import folium
import requests
from flask import Flask, render_template, url_for, request
from flask_table import Table, Col
from folium.plugins import HeatMap
from geopy.geocoders import Nominatim
from tqdm import tqdm

RKI_API = 'https://services7.arcgis.com/mOBPykOjAyBO2ZKk/arcgis/rest/services/' \
          'RKI_Landkreisdaten/FeatureServer/0/query?where=1%3D1&outFields=*&outSR=4326&f=json'
COORDINATES_FILEPATH = 'german_county_coordinates.json'
NUTS_POSTAL_CODES = 'pc2020_DE_NUTS-2021_v3.0.csv'
START_POSITION = (50.993763, 10.162379)

API_DATA: dict
FOLIUM_MAP: folium.Map
GEOLOCATOR: Nominatim


app = Flask(__name__)


class DistrictTable(Table):
    """Flask table class."""
    district_name = Col('District')
    cases7_per_100k = Col('District 7d/100k')
    state = Col('State')
    cases7_bl_per_100k = Col('State 7d/100k')
    allow_sort = True

    def sort_url(self, col_key, reverse=False):
        """Sort table."""
        if reverse:
            direction = 'desc'
        else:
            direction = 'asc'
        return url_for('main', sort=col_key, direction=direction)


def setup():
    """Setup required elements."""
    global API_DATA
    global FOLIUM_MAP
    global GEOLOCATOR
    API_DATA = get_api_data()
    FOLIUM_MAP = folium.Map(
        location=START_POSITION, zoom_start=6, tiles='Stamen toner', min_zoom=6, max_zoom=9)
    GEOLOCATOR = Nominatim(user_agent="covid-tracker-germany")
    if not os.path.exists(COORDINATES_FILEPATH):
        update_coordinates()


def get_nuts_table() -> dict:
    """
    Get postal code from NUTS code.

    :return: NUTS table code -> {<NUTS>: <postal_code>}
    """
    with open(NUTS_POSTAL_CODES) as file:
        file_reader = csv.DictReader(file, delimiter=';')
        nuts_table = {}
        for row in file_reader:
            nuts3 = row['NUTS3'].replace("'", "")
            postal_code = row['CODE'].replace("'", "")
            if nuts3 in nuts_table:
                continue
            nuts_table.update({nuts3: postal_code})
    return nuts_table


def update_coordinates():
    """Update German county coordinates."""
    response = requests.get(url=RKI_API)
    data = json.loads(response.text)
    nuts_table = get_nuts_table()
    coordinates = {}
    for district in tqdm(data['features']):
        district = district['attributes']
        if 'Berlin' not in district['GEN']:
            district_name = f"{district['GEN']} {district['BEZ']}"
            district_postal_code = nuts_table[district['NUTS']]
            latitude, longitude = get_coordinates(district_postal_code)
        else:
            district_name = 'Berlin'
            latitude, longitude = get_coordinates('Berlin')
        coordinates.update({district_name: (latitude, longitude)})
    with open(COORDINATES_FILEPATH, 'w') as json_export:
        json.dump(coordinates, json_export, indent=4, ensure_ascii=False)


def get_coordinates(search_query) -> tuple:
    """
    Get coordinates.

    :param search_query: search query to retrieve coordinates
    :return: latitude and longitude coordinates
    """
    search_query += ' Germany'
    location = GEOLOCATOR.geocode(query=search_query)
    if not location:
        print('No coordinates for', search_query)
        return 0, 0
    return location.latitude, location.longitude


def load_coordinates():
    """Load German county coordinates."""
    with open('german_county_coordinates.json') as json_import:
        return json.load(json_import)


def add_circle(latitude: float, longitude: float, county: str, weight: float):
    """
    Add circle to map.

    :param latitude: location latitude
    :param longitude: location longitude
    :param county: location county
    :param weight: COVID incidence rate

    """
    circle = folium.Circle(
        location=(latitude, longitude),
        color="white",
        tooltip=f'{county} {round(weight, 2)}'
    )
    circle.add_to(FOLIUM_MAP)


def get_api_data() -> dict:
    """Get data from API."""
    response = requests.get(url=RKI_API)
    data = json.loads(response.text)
    return data


def get_heatmap() -> str:
    """Get heatmap in HTML."""
    heatmap_data = []
    coordinates = load_coordinates()
    district_dict = {}
    for district in API_DATA['features']:
        district = district['attributes']
        if 'Berlin' not in district['GEN']:
            district_name = f"{district['GEN']} {district['BEZ']}"
        else:
            if 'Berlin' in district_dict:
                continue
            district_name = 'Berlin'
            district['cases7_per_100k'] = district['cases7_bl_per_100k']
        latitude, longitude = coordinates[district_name]
        add_circle(latitude=latitude, longitude=longitude, county=district_name,
                   weight=district['cases7_per_100k'])
        district_dict.update({
            district_name: {'latitude': latitude,
                            'longitude': longitude,
                            'weight': district['cases7_per_100k']}
        })
        heatmap_data.append([latitude, longitude, district['cases7_per_100k']])
    HeatMap(heatmap_data, radius=50, max_zoom=10, min_opacity=0.1).add_to(FOLIUM_MAP)
    return FOLIUM_MAP._repr_html_()


@app.route('/test/')
def get_table() -> str:
    """Get data table in HTML."""
    table_data = []
    for district in API_DATA['features']:
        district = district['attributes']
        district_name = f"{district['GEN']} {district['BEZ']}"
        table_data.append({
            'district_name': district_name,
            'state': district['BL'],
            'cases7_per_100k': round(district['cases7_per_100k'], 2),
            'cases7_bl_per_100k': round(district['cases7_bl_per_100k'], 2)
        })
    sort = request.args.get('sort', 'district_name')
    reverse = (request.args.get('direction', 'asc') == 'desc')
    table_data = sorted(table_data, key=itemgetter(sort), reverse=reverse)
    table = DistrictTable(table_data, sort_by=sort, sort_reverse=reverse)
    return table.__html__()


@app.route('/')
def main():
    """Flask app root."""
    heatmap = get_heatmap()
    table = get_table()
    return render_template("index.html", table=table, heatmap=heatmap)


if __name__ == '__main__':
    setup()
    app.run(debug=True)
