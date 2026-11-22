"""Independent demo branch node. Run multiple copies on different ports."""
import os
from flask import Flask, jsonify, request

app = Flask(__name__)
BRANCH_ID = os.getenv('BRANCH_ID', 'A')
PORT = int(os.getenv('PORT', '5001'))
# Demo-only in-memory state. Replace with SQLite and locking before concurrent use.
state = {'branch_id': BRANCH_ID, 'cash': 10000, 'employees': 5, 'minimum_reserve': 2000}

@app.get('/status')
def status():
    return jsonify({**state, 'reserve_warning': state['cash'] < state['minimum_reserve']})

@app.post('/deposit')
def deposit():
    data = request.get_json(silent=True) or {}
    amount = data.get('amount')
    if type(amount) is not int or amount <= 0:
        return jsonify({'error': 'amount must be a positive integer in cents'}), 400
    state['cash'] += amount
    return jsonify({'branch_id': BRANCH_ID, 'cash': state['cash']})

@app.post('/withdraw')
def withdraw():
    data = request.get_json(silent=True) or {}
    amount = data.get('amount')
    if type(amount) is not int or amount <= 0:
        return jsonify({'error': 'amount must be a positive integer in cents'}), 400
    if state['cash'] - amount < state['minimum_reserve']:
        return jsonify({'error': 'insufficient cash above minimum reserve'}), 409
    state['cash'] -= amount
    return jsonify({'branch_id': BRANCH_ID, 'cash': state['cash']})

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=PORT, debug=False)
