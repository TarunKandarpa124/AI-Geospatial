from flask import Flask, request, render_template, jsonify, session
from geopy.geocoders import Nominatim
import time
import openrouteservice
import overpy
import regex
from timezonefinder import TimezoneFinder
import requests
import pytz
from datetime import datetime
import google.generativeai as genai
import secrets
import sqlite3




app = Flask(__name__)
app.secret_key = secrets.token_urlsafe(32)


GOOGLE_API_KEY = 'AIzaSyBEymVM_zPtRmSf3udgZx-r_4EIa7-yDCs'
genai.configure(api_key=GOOGLE_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

ORS_API_KEY = '5b3ce3597851110001cf62488b1a1a63d9f84aa3a7326a2b94d66f28'
ors_client = openrouteservice.Client(key=ORS_API_KEY)

OWM_API_KEY = '4b5eb9fbbe2555fbbb42f8f8b97e9222'

geolocator = Nominatim(user_agent="my-geocoding-app/1.0")

def identify_query(query):
    prompt = f"identify and just return only the type of query that is being asked whether it is about Single_Location (i.e. if the user is asking about only a single location where is so and so or tell something about this place or tell something interesting about the place or give description about this place or give me its land area or population count of that place ) or  POI (i.e. if the user is asking for multiple locations from a central location with or without range), or Route (i.e. asking for route or distance or both between two places or how far one place is from another, or how to travel from one place to another) or General (i.e. if the the user query is neither of the types like single location nor poi nor desription), user_location (i.e. if the user is asking to find current location or asking about his location), just return only the type of query dont write any sentence: {query}"
    response = model.generate_content(prompt)
    if hasattr(response, 'text'):
        response_text = response.text.replace('*', '').replace('**', '').replace('##', '').replace('\n', '')
        return response_text.lower()
    else:
        return "No response text found."

'''
def get_population_density(latitude, longitude, radius=1):  # Default radius is 1km
    try:
        pop_density = worldpops.get_pop_density(
            latitude, longitude, dataset="ppp_2020_1km_Aggregated", radius=radius
        )
        return pop_density
    except Exception as e:
        print(f"Error getting population density: {e}")
        return None
'''


def init_db():
    conn = sqlite3.connect('geo_chat_history.db')  # Create or connect to the database file
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_query TEXT NOT NULL,
            bot_response TEXT NOT NULL
        )
    ''')
    conn.commit()
    conn.close()


# Call the function to initialize the database when the app starts
init_db()

def handle_population_density_request(query):
    prompt = f"""
    From the user query: "{query}", 
    extract the following information:
    1. Location name: The place for which population density is requested.
    2. Radius (in kilometers): The radius around the location, if specified. 
       If no radius is mentioned, assume 10 km. RETURN ONLY THESE TWO, DONT WRITE ANYTHING ELSE IRRELAVANT
    """
    response = model.generate_content(prompt)
    if hasattr(response, 'text'):
        response_text = response.text.replace('*', '').replace('**', '').replace('##', '').replace('\n', '')
        return response_text
    else:
        return "No response text found."

    try:
        location_name = response_text.split("Location name:")[1].split("\n")[0].strip()
        radius_line = response_text.split("Radius (in kilometers):")[1].split("\n")[0].strip()
        radius = int(radius_line) if radius_line.isdigit() else 1  # Default to 1km
    except IndexError:
        return {'chatbox_response': "Could not understand the location or radius in your query."}

    pop_density = get_population_density(location_name.latitude, location_name.longitude, radius)

    if pop_density is not None:
        response_text = f"Population Density in {location_name} (within {radius}km): {pop_density:.2f} people/km²"
        map_data = [{
            'type': 'marker',
            'lat': location_name.latitude,
            'lng': location_name.longitude,
            'popupContent': response_text
        }]
        return {'chatbox_response': response_text, 'map_data': map_data}
    else:
        return {'chatbox_response': "Population density data not available for this location."}


def generate_general_response(info):
    prompt = f"just frame a proper sentence from {info} being asked without skipping even slightest of the part of the {info}, give a big user friendly response based on the info being said and asked give it in big brief response, dont write anything else as an introduction like 'okay , here is user friendly response' or any similar beggining statements, nobeginning titles addressing before the actual response, just give me direct response, dont use ':' : {info}"
    response = model.generate_content(prompt)  # Assuming model.generate_content returns a requests.Response object

    if hasattr(response, 'text'):
        response_text = response.text.replace('*', '').replace('**', '').replace('##', '').replace('\n', '')
        return response_text  # Return the extracted text if available
    else:
        # If response doesn't have 'text', try to get JSON content
        try:
            return response.json()  # Attempt to get JSON content if possible
        except (AttributeError, ValueError):
            # Handle cases where response is not JSON-serializable
            return "No response text found or could not be serialized."  # Or another appropriate message

def generate_description(info):
    prompt = f"summarize results and responses BY FRAMING PROPER SENTENCES IN ORDER TO WHAT IS BEING ASKED FIRST IN THE {info} along with lat and longs if found from the given in user firendly manner response, if at all response is way too big,  info, dont write anything else as an introduction like 'okay , here is user friendly response' or any similar beggining statements, nobeginning titles addressing before the actual response, just give me direct response, dont use ':' : {info}"
    response = model.generate_content(prompt)
    if hasattr(response, 'text'):
        response_text = response.text.replace('*', '').replace('**', '').replace('##', '').replace('\n', '')
        return response_text
    else:
        return "No response text found."


def handle_user_location(latitude, longitude):
    url = f"https://nominatim.openstreetmap.org/reverse?format=jsonv2&lat={latitude}&lon={longitude}&zoom=18&addressdetails=1&extratags=1"
    headers = {
        'User-Agent': 'my-geocoding-app/1.0 (tarunkandarpa124@gmail.com)'
    }
    response = requests.get(url, headers=headers)
    print(response.status_code)
    print(response.content)
    data = response.json()
    address = data.get('display_name', "Location not found")

    weather_url = f"http://api.openweathermap.org/data/2.5/weather?lat={latitude}&lon={longitude}&appid={OWM_API_KEY}&units=metric"
    response_weather = requests.get(weather_url)
    weather_data = response_weather.json()

    if response_weather.status_code == 200:
        temperature = weather_data['main']['temp']
        description1 = weather_data['weather'][0]['description']
        wind_speed = weather_data['wind']['speed']

    tf = TimezoneFinder()

    timezone_str = tf.timezone_at(lat=latitude, lng=longitude)

    if timezone_str:
        timezone = pytz.timezone(timezone_str)
        local_time = datetime.now(timezone)

    map_data = [{
        'type': 'marker',
        'lat': latitude,
        'lng': longitude,
        'popupContent': f"{address}<br>Latitude: {latitude}<br>Longitude: {longitude}"
    }]
    response_text = f"Just frame an answer with {address}, {latitude} and {longitude} saying that you (i.e. the user to whom you are answering) are currently residing in these location, instead of using i am in your response, use 'you are' and use 'your' instead of 'me', also mention about {temperature}, {wind_speed}, {description1}, {local_time} of  that place "
    response1 = generate_general_response(response_text)
    return {
        'chatbox_response': response1,
        'map_data': map_data
    }

def handle_single_location(query):
    prompt = f"Extract only the main important place/building/location/entity name which is being asked in the query, dont write anything else: {query}"
    try:
        response = model.generate_content(prompt)
    except genai.errors.InternalServerError:
        print("Internal server error encountered. Retrying in 5 seconds...")
        time.sleep(2)
        response = model.generate_content(prompt)

    if hasattr(response, 'text'):
        response_text = response.text.replace('*', '').replace('**', '').replace('\n', '')
        place_name = response_text
        first_part = place_name.split(',')[0]
        location = geolocator.geocode(first_part, timeout=10)


        if location:

            map_data = [{
                'type': 'marker',
                'lat': location.latitude,
                'lng': location.longitude,
                'popupContent': f"{location}<br>{location.address}<br>Latitude: {location.latitude}<br>Longitude: {location.longitude}"
            }]

            weather_url = f"http://api.openweathermap.org/data/2.5/weather?lat={location.latitude}&lon={location.longitude}&appid={OWM_API_KEY}&units=metric"
            response_weather = requests.get(weather_url)
            weather_data = response_weather.json()

            if response_weather.status_code == 200:
                temperature = weather_data['main']['temp']
                description1 = weather_data['weather'][0]['description']
                wind_speed = weather_data['wind']['speed']

            tf = TimezoneFinder()

            timezone_str = tf.timezone_at(lat=location.latitude, lng=location.longitude)

            if timezone_str:
                timezone = pytz.timezone(timezone_str)
                local_time = datetime.now(timezone)


            x = (
                f"Location: {first_part}\n"
                f"Latitude: {location.latitude}\n"
                f"Longitude: {location.longitude}\n"
                f"Address: {location.address}\n"
                f"Temperature: {temperature}°C\n"
                f"Wind Speed: {wind_speed} m/s\n"
                f"Local Time: {local_time}\n"
                f"Weather Description: {description1}"
            )

            y = (
                f"Location: {first_part}\n"
                f"Latitude: {location.latitude}\n"
                f"Longitude: {location.longitude}\n"
                f"Address: {location.address}\n"
                f"Local Time: {local_time}\n"
                f"Temperature: {temperature}°C\n"
                f"Wind Speed: {wind_speed} m/s\n"
                f"description: {description1}"
            )
            description = generate_general_response(query)
            description2 = generate_description(y)
            response1 = f"From query {query}, give that answer to {query} from both {description2} and {description} and then summarize {description2}\n{description}"  # This would be YOUR code to generate the text response
            response = generate_general_response(response1)
            return {
                'chatbox_response': response,
                'map_data': map_data
            }
        else:
            return {'chatbox_response': generate_general_response(query)}
    else:
        return generate_general_response(query)


def handle_route_request(query):
    #global base_map
    prompt = f"Extract only the two main important place names which is found in the query and also transportation mode (driving, cycling, walkingwhich is required for the route, dont write anything else: {query}"
    try:
        response = model.generate_content(prompt)
    except genai.errors.InternalServerError:
        print("Internal server error encountered. Retrying in 5 seconds...")
        time.sleep(2)
        response = model.generate_content(prompt)

    if hasattr(response, 'text'):
        response_text = response.text.replace('*', '').replace('**', '').replace('\n', '')
        places = [place.strip().replace('-', '') for place in response_text.split(',') if place.strip()]
        two_place = [part for part in places[0].split(" ") if part]
        transportation_mode = places[-1] if len(places) > 2 else "driving"

        if len(places) < 2:
            return {'chatbox_response': generate_general_response(query)}

        origin = places[0]
        destination = places[1]

        origin_location = geolocator.geocode(origin, timeout=10)
        destination_location = geolocator.geocode(destination, timeout=10)

        if origin_location and destination_location:

            profile_map = {
                "driving": "driving-car",
                "cycling": "cycling-regular",
                "walking": "foot-walking"
            }
            profile = profile_map.get(transportation_mode, "driving-car")


            route = ors_client.directions(
                coordinates=[[origin_location.longitude, origin_location.latitude],
                             [destination_location.longitude, destination_location.latitude]],
                profile=profile,
                format='geojson'
            )

            distance = route['features'][0]['properties']['segments'][0]['distance'] / 1000
            steps = route['features'][0]['properties']['segments'][0]['steps']
            instructions = []
            for step in steps:
                instruction = step['instruction']
                instructions.append(instruction)

            route_description = generate_description(f"the distance between {origin} and {destination} is {distance}\n" + "Route Instructions:<br>" + "<br>".join(instructions))

            coordinates = route['features'][0]['geometry']['coordinates']
            map_data = [
                {
                    'type': 'polyline',
                    'coordinates': [[coord[1], coord[0]] for coord in coordinates]
                },
                {  # Add marker for origin
                    'type': 'marker',
                    'lat': origin_location.latitude,
                    'lng': origin_location.longitude,
                    'popupContent': f"Origin: {origin}<br>Coordinates: {origin_location.latitude}, {origin_location.longitude}"
                },
                {  # Add marker for destination
                    'type': 'marker',
                    'lat': destination_location.latitude,
                    'lng': destination_location.longitude,
                    'popupContent': f"Destination: {destination}<br>Coordinates: {destination_location.latitude}, {destination_location.longitude}"
                }
            ]

            general_route_description = generate_general_response(f"{query}")
            response = f"{general_route_description}\n{route_description}"
            return {
                'chatbox_response': response,  # Your generated response text
                'map_data': map_data
            }
        else:
            return {'chatbox_response': generate_general_response(query)}  # Handle location not found
    else:
        return generate_general_response(query)
def handle_poi_request(query):
    prompt = f"Extract the main center location, range in meters (if mentioned), and POI type from this query: {query}. Provide the result in this format: 'location: <location>, range: <range>, poi_type: <type>'. Convert plural POI types to singular, if no range is mentioned in the query, then consider the default range as 5000 meters and continue."

    try:
        response = model.generate_content(prompt)
    except genai.errors.InternalServerError:
        print("Internal server error encountered. Retrying in 5 seconds...")
        time.sleep(2)
        response = model.generate_content(prompt)

    if hasattr(response, 'text'):
        response_text = response.text.replace('*', '').replace('**', '').replace('\n', ' ')

        location_match = regex.search(r"location:\s*([a-zA-Z\s,]+),\s*range:\s*(None|Not Mentioned|\d+),\s*poi_type:\s*([a-zA-Z\s]+)", response_text, regex.IGNORECASE)

        if location_match:
            location_name = location_match.group(1).strip()
            range_in_meters = location_match.group(2)
            poi_type = location_match.group(3).strip().lower()

            if range_in_meters.lower() in ['none', 'not mentioned']:
                range_in_meters = 5000
            else:
                range_in_meters = int(range_in_meters)

            location = geolocator.geocode(location_name, timeout=10)

            if location:
                lat, lon = location.latitude, location.longitude

                poi_type_to_osm_tag = {
                    "restaurant": ("amenity", "restaurant"),
                    "hospital": ("amenity", "hospital"),
                    "park": ("leisure", "park"),
                    "school": ("amenity", "school"),
                    "hotel": ("tourism", "hotel"),
                    "atm": ("amenity", "atm"),
                    "pharmacy": ("amenity", "pharmacy"),
                    "bank": ("amenity", "bank"),
                    # --- New additions ---
                    "cafe": ("amenity", "cafe"),
                    "coffee shop": ("amenity", "cafe"),  # Synonym for cafe
                    "bar": ("amenity", "bar"),
                    "pub": ("amenity", "pub"),
                    "nightclub": ("amenity", "nightclub"),
                    "cinema": ("amenity", "cinema"),
                    "theatre": ("amenity", "theatre"),
                    "museum": ("tourism", "museum"),
                    "gallery": ("tourism", "gallery"),
                    "library": ("amenity", "library"),
                    "university": ("amenity", "university"),
                    "college": ("amenity", "college"),
                    "supermarket": ("shop", "supermarket"),
                    "grocery store": ("shop", "supermarket"),  # Synonym for supermarket
                    "convenience store": ("shop", "convenience"),
                    "bakery": ("shop", "bakery"),
                    "butcher": ("shop", "butcher"),
                    "clothes shop": ("shop", "clothes"),
                    "shoe shop": ("shop", "shoes"),
                    "electronics store": ("shop", "electronics"),
                    "department store": ("shop", "department_store"),
                    "hardware store": ("shop", "hardware"),
                    "furniture store": ("shop", "furniture"),
                    "bookshop": ("shop", "books"),
                    "post office": ("amenity", "post_office"),
                    "police station": ("amenity", "police"),
                    "fire station": ("amenity", "fire_station"),
                    "doctor": ("amenity", "doctors"),
                    "dentist": ("amenity", "dentist"),
                    "veterinary": ("amenity", "veterinary"),
                    "fuel": ("amenity", "fuel"),
                    "parking": ("amenity", "parking"),
                    "bus stop": ("highway", "bus_stop"),
                    "train station": ("railway", "station"),
                    "airport": ("aeroway", "aerodrome"),
                    # ... add even more as needed ...
                }

                osm_tag, tag_value = poi_type_to_osm_tag.get(poi_type, (None, None))

                if osm_tag and tag_value:
                    overpass_api = overpy.Overpass()
                    overpass_query = f"""
                    [out:json];
                    (
                      node["{osm_tag}"="{tag_value}"](around:{range_in_meters}, {lat}, {lon});
                      way["{osm_tag}"="{tag_value}"](around:{range_in_meters}, {lat}, {lon});
                      relation["{osm_tag}"="{tag_value}"](around:{range_in_meters}, {lat}, {lon});
                    );
                    out body;
                    """

                    try:
                        result = overpass_api.query(overpass_query)
                        pois = []
                        for node in result.nodes:
                            address = geolocator.reverse((node.lat, node.lon)).address if node.lat and node.lon else "Address not found"
                            pois.append({
                                'name': node.tags.get('name', 'Unnamed'),
                                'lat': float(node.lat),
                                'lon': float(node.lon),
                                'type': node.tags.get(osm_tag, 'Unknown'),
                                'address': address
                            })

                        if pois:
                            map_data = [{
                                'type': 'marker',
                                'lat': poi['lat'],
                                'lng': poi['lon'],
                                'popupContent': (
                                    f"<strong>Name:</strong> {poi['name']}<br>"
                                    f"<strong>Type:</strong> {poi['type']}<br>"
                                    f"<strong>Latitude:</strong> {poi['lat']}<br>"
                                    f"<strong>Longitude:</strong> {poi['lon']}<br>"
                                    f"<strong>Address:</strong> {poi['address']}"
                                )
                            } for poi in pois]

                            x = f"Found {len(pois)} points of interest for '{poi_type}' within {range_in_meters} meters of {location_name}."
                            poi_description = generate_description(f"{pois}")
                            response = f"{x}\n{poi_description}"
                            return {
                                'chatbox_response': response,
                                'map_data': map_data
                            }

                        else:
                            location = geolocator.geocode(location_name, timeout=5)
                            map_data = [{
                                'type': 'marker',
                                'loc': location_name,
                                'lat': location.latitude,
                                'lng': location.longitude,
                                'popupContent': f"{location}<br>{location.address}<br>Latitude: {location.latitude}<br>Longitude: {location.longitude}"
                            }]
                            response = f"{generate_general_response(query)}"
                            return {
                                'chatbox_response': response,
                                'map_data': map_data
                            }

                    except Exception as e:
                        return f"Error querying Overpass API: {str(e)}"
                else:
                    # Handle case where POI type is not in the mapping
                    return {'chatbox_response': generate_general_response(query)}

            else:
                return {'chatbox_response': generate_general_response(query)}
        else:
            return {'chatbox_response': generate_general_response(query)}
    else:
        return generate_general_response(query)


def handle_dynamic_query(query, latitude=None, longitude=None):
    history = session.get('history', [])


    if any(keyword in query.lower() for keyword in ["it", "its", "it's", "that", "there", "this", "these"]):
        previous_response = history[-1]['response'] if history else ""

        # Check if previous response was user location
        if "Your current location is:" in previous_response or session.get('user_location'):
            # If previous response was user location, use info from there, otherwise from session
            if "Your current location is:" in previous_response:
                location_match = regex.search(r"Your current location is: (.*?) \(Latitude:", previous_response)
                location_name = location_match.group(1) if location_match else ""
            else:
                user_location = session.get('user_location')
                location_name = user_location['address'] if user_location else ""
                latitude = user_location['latitude'] if user_location else None
                longitude = user_location['longitude'] if user_location else None

            prompt = f"Considering the user's current location is '{location_name}', answer this: {query}"

        else:
            prompt = f"Considering the previous response: '{previous_response}', answer this {query}"
    else:
        prompt = query

    # Check if query is a user location query


    response1 = identify_query(prompt)

    if response1:
        lower_response = response1.lower().strip()

        if lower_response == "route":
            response_data = handle_route_request(prompt)
        elif lower_response == "user_location":
            # If user location is already in session, use that
            if session.get('user_location'):
                user_location = session.get('user_location')
                response_data = handle_user_location(user_location['latitude'], user_location['longitude'])
            else:  # Otherwise, get it from the current request (if available)
                if latitude and longitude:
                    response_data = handle_user_location(latitude, longitude)
                else:
                    response_data = {'chatbox_response': "Unable to get your location."}
        elif lower_response in ["poi", "places"]:
            response_data = handle_poi_request(query)
        #elif lower_response == "popden":
        #    response_data = handle_population_density_request(prompt)
        elif lower_response == "single_location":
            response_data = handle_single_location(prompt)
        else:
            result = generate_general_response(prompt)
            response_data = {'chatbox_response': result}

        if isinstance(response_data, dict) and 'chatbox_response' in response_data:
            session['history'] = history + [{'query': query, 'response': response_data['chatbox_response']}]
        else:
            session['history'] = history + [{'query': query, 'response': "Error: Could not process the query."}]

        if isinstance(response_data, dict) and 'chatbox_response' in response_data:
            conn = sqlite3.connect('geo_chat_history.db')
            cursor = conn.cursor()
            cursor.execute("INSERT INTO chat_history (user_query, bot_response) VALUES (?, ?)",
                           (query, response_data['chatbox_response']))
            conn.commit()
            conn.close()

        return response_data


@app.route('/')
def index():
    return render_template('map1_1.html')



@app.route('/api/generate_polygon_response', methods=['POST'])
def generate_polygon_response():
    prompt = request.json.get('prompt')
    response = model.generate_content(prompt)  # Assuming model.generate_content returns a requests.Response object

    if hasattr(response, 'text'):
        response_text = response.text.replace('*', '').replace('**', '').replace('##', '').replace('\n', '')
        #return response_text
        return jsonify({'response': response_text})



@app.route('/api/geoquery', methods=['POST'])
def geoquery():
    query = request.json.get('query')
    latitude = request.json.get('latitude')  # Get latitude from request
    longitude = request.json.get('longitude')
    response_data = handle_dynamic_query(query, latitude, longitude)
    return jsonify(response_data)


@app.route('/api/map_click', methods=['POST'])
def map_click():
    latitude = request.json.get('latitude')
    longitude = request.json.get('longitude')

    # 1. Reverse Geocoding (Get address)
    location = geolocator.reverse((latitude, longitude), timeout=10)
    address = location.address if location else "Address not found"

    # 2. Timezone
    tf = TimezoneFinder()
    timezone_str = tf.timezone_at(lat=latitude, lng=longitude)
    timezone = pytz.timezone(timezone_str) if timezone_str else None
    local_time = datetime.now(timezone).strftime('%Y-%m-%d %H:%M:%S %Z%z') if timezone else "Timezone not found"

    # 3. Temperature (Using OpenWeatherMap API)
    weather_url = f"http://api.openweathermap.org/data/2.5/weather?lat={latitude}&lon={longitude}&appid={OWM_API_KEY}&units=metric"
    response_weather = requests.get(weather_url)
    temperature = "Temperature not found"
    if response_weather.status_code == 200:
        weather_data = response_weather.json()
        temperature = weather_data['main']['temp']

    # 4. Create response
    response_text = f"write the following in your own words , start with :- 'The clicked location on map appears to be Latitude:{latitude}\nLongitude: {longitude}\n**Address: {address}\nTimezone: {local_time}\nTemperature: {temperature}°C'"
    response1 = generate_general_response(response_text)
    map_data = [{
        'type': 'marker',
        'lat': latitude,
        'lng': longitude,
        'popupContent': f"Latitude: {latitude}<br>Longitude: {longitude}<br>Address:{address}"
    }]

    conn = sqlite3.connect('geo_chat_history.db')
    cursor = conn.cursor()
    # You might want to extract a specific part of response1 as the user query here
    user_query_from_click = response1.split("appears to be")[0]  # Or some extracted part
    cursor.execute("INSERT INTO chat_history (user_query, bot_response) VALUES (?, ?)",
                   (user_query_from_click, response1))
    conn.commit()
    conn.close()

    return {
        'chatbox_response': response1,
        'map_data': map_data}


if __name__ == '__main__':
    app.run(debug=True)