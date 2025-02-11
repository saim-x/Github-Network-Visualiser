import requests
from flask import Flask, render_template, request, jsonify
from collections import deque
import logging
import time
from dotenv import load_dotenv
import os

app = Flask(__name__)

# Configuration
MAX_USERS_PER_LEVEL = 99
DEPTH_LIMIT = 1
GITHUB_API_HEADERS = {
    'Authorization': f'token {os.getenv("GITHUB_TOKEN")}' # Use your own token here
}

logging.basicConfig(level=logging.DEBUG)

def handle_rate_limit(response):
    remaining = int(response.headers.get('X-RateLimit-Remaining', 0))
    if remaining < 10:
        reset_time = int(response.headers.get('X-RateLimit-Reset', 0))
        current_time = int(time.time())
        wait_time = max(reset_time - current_time, 0)
        logging.warning(f"Rate limit running low. {remaining} requests remaining. Reset in {wait_time} seconds")
    return remaining

def get_user_info(username, headers):
    url = f'https://api.github.com/users/{username}'
    response = requests.get(url, headers=headers)
    handle_rate_limit(response)
    
    if response.status_code != 200:
        logging.error(f"Failed to fetch user info: {response.status_code} - {response.text}")
        return None
        
    data = response.json()
    user_info = {
        'login': data['login'],
        'avatar_url': data['avatar_url'],
        'followers_count': data.get('followers', 0),
        'following_count': data.get('following', 0),
        'public_repos': data.get('public_repos', 0),
        'name': data.get('name', ''),
        'company': data.get('company', ''),
        'location': data.get('location', '')
    }
    return user_info

def get_github_data(url, headers):
    response = requests.get(url, headers=headers)
    handle_rate_limit(response)
    
    if response.status_code != 200:
        return []
    return response.json()

def build_graph(target_username, headers):
    target_user = get_user_info(target_username, headers)
    if not target_user:
        return None

    queue = deque([(target_user['login'], 0, target_user)])
    processed = set()
    nodes = []
    edges = []
    
    while queue:
        username, depth, user_data = queue.popleft()
        
        if username in processed or depth > DEPTH_LIMIT:
            continue
            
        processed.add(username)
        
        nodes.append({
            'data': {
                'id': username,
                'avatar': user_data['avatar_url'],
                'label': username,
                'followers': user_data.get('followers_count', 0),
                'following': user_data.get('following_count', 0),
                'repos': user_data.get('public_repos', 0),
                'name': user_data.get('name', ''),
                'company': user_data.get('company', ''),
                'location': user_data.get('location', ''),
                'depth': depth
            }
        })

        if depth < DEPTH_LIMIT:
            followers = get_github_data(f'https://api.github.com/users/{username}/followers', headers)[:MAX_USERS_PER_LEVEL]
            following = get_github_data(f'https://api.github.com/users/{username}/following', headers)[:MAX_USERS_PER_LEVEL]

            for connection in followers + following:
                conn_username = connection['login']
                conn_info = get_user_info(conn_username, headers)
                if not conn_info:
                    continue

                edge_type = 'follows' if connection in following else 'followed_by'
                edge_id = f"{username}-{conn_username}" if edge_type == 'follows' else f"{conn_username}-{username}"
                
                if not any(e['data']['id'] == edge_id for e in edges):
                    edges.append({
                        'data': {
                            'id': edge_id,
                            'source': username if edge_type == 'follows' else conn_username,
                            'target': conn_username if edge_type == 'follows' else username,
                            'type': edge_type
                        }
                    })

                if conn_username not in processed:
                    queue.append((conn_username, depth + 1, conn_info))

    # Collect depth 1 users and existing edges
    depth1_users = {node['data']['id'] for node in nodes if node['data']['depth'] == 1}
    existing_edges = {(edge['data']['source'], edge['data']['target']) for edge in edges}

    # Check interconnections between depth 1 users
    for user in depth1_users:
        following = get_github_data(f'https://api.github.com/users/{user}/following', headers)[:MAX_USERS_PER_LEVEL]
        for followed_user in following:
            followed_username = followed_user['login']
            if followed_username in depth1_users:
                if (user, followed_username) not in existing_edges:
                    edge_id = f"{user}-{followed_username}"
                    edges.append({
                        'data': {
                            'id': edge_id,
                            'source': user,
                            'target': followed_username,
                            'type': 'follows'
                        }
                    })
                    existing_edges.add((user, followed_username))

    logging.debug(f"Graph built with {len(nodes)} nodes and {len(edges)} edges.")
    return {
        'nodes': nodes,
        'edges': edges
    }

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/graph', methods=['POST'])
def generate_graph():
    username = request.form.get('username')
    user_token = request.form.get('token')
    
    if not username:
        return jsonify({'error': 'Username required'}), 400

    # Use user's token if provided, otherwise use default
    headers = GITHUB_API_HEADERS
    if user_token:
        headers = {'Authorization': f'token {user_token}'}

    graph_data = build_graph(username, headers)  # Pass headers to build_graph
    if graph_data:
        return jsonify(graph_data)
    else:
        return jsonify({'error': 'User not found'}), 404

if __name__ == '__main__':
    app.run(debug=True)