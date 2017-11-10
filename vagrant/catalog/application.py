from flask import Flask, render_template, request, redirect, url_for, flash
from sqlalchemy import create_engine, asc
from sqlalchemy.orm import sessionmaker
from database_setup import Base, Category, Item, User
from flask import jsonify
import collections

from flask import session as login_session
import random
import string

# IMPORTS FOR THIS STEP
from oauth2client.client import flow_from_clientsecrets
from oauth2client.client import FlowExchangeError
import httplib2
import json
from flask import make_response
import requests
from functools import wraps

app = Flask(__name__)


CLIENT_ID = json.loads(
    open('client_secrets.json', 'r').read())['web']['client_id']
APPLICATION_NAME = "Star Wars Catalog"

engine = create_engine('sqlite:///itemcatalogwithusers.db')

DBSession = sessionmaker(bind=engine)
session = DBSession()

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in login_session:
            return redirect('/login')
        return f(*args, **kwargs)
    return decorated_function

@app.route('/gconnect', methods=['POST'])
def gconnect():
    # Validate state token
    if request.args.get('state') != login_session['state']:
        response = make_response(json.dumps('Invalid state parameter.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response
    # Obtain authorization code
    code = request.data

    try:
        # Upgrade the authorization code into a credentials object
        oauth_flow = flow_from_clientsecrets('client_secrets.json', scope='')
        oauth_flow.redirect_uri = 'postmessage'
        credentials = oauth_flow.step2_exchange(code)
    except FlowExchangeError:
        response = make_response(
            json.dumps('Failed to upgrade the authorization code.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Check that the access token is valid.
    access_token = credentials.access_token
    url = ('https://www.googleapis.com/oauth2/v1/tokeninfo?access_token=%s'
           % access_token)
    h = httplib2.Http()
    result = json.loads(h.request(url, 'GET')[1])
    # If there was an error in the access token info, abort.
    if result.get('error') is not None:
        response = make_response(json.dumps(result.get('error')), 500)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Verify that the access token is used for the intended user.
    gplus_id = credentials.id_token['sub']
    if result['user_id'] != gplus_id:
        response = make_response(
            json.dumps("Token's user ID doesn't match given user ID."), 401)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Verify that the access token is valid for this app.
    if result['issued_to'] != CLIENT_ID:
        response = make_response(
            json.dumps("Token's client ID does not match app's."), 401)
        print "Token's client ID does not match app's."
        response.headers['Content-Type'] = 'application/json'
        return response

    stored_access_token = login_session.get('access_token')
    stored_gplus_id = login_session.get('gplus_id')
    if stored_access_token is not None and gplus_id == stored_gplus_id:
        response = make_response(json.dumps('Current user is already connected.'),
                                 200)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Store the access token in the session for later use.
    login_session['access_token'] = credentials.access_token
    login_session['gplus_id'] = gplus_id

    # Get user info
    userinfo_url = "https://www.googleapis.com/oauth2/v1/userinfo"
    params = {'access_token': credentials.access_token, 'alt': 'json'}
    answer = requests.get(userinfo_url, params=params)

    data = answer.json()

    login_session['username'] = data['name']
    login_session['picture'] = data['picture']
    login_session['email'] = data['email']

    # see if user exists, if it doesn't make a new one
    user_id = getUserID(login_session['email'])
    if not user_id:
        user_id = createUser(login_session)
    login_session['user_id'] = user_id

    output = ''
    output += '<h1>Welcome, '
    output += login_session['username']
    output += '!</h1>'
    output += '<img src="'
    output += login_session['picture']
    output += ' " style = "width: 300px; height: 300px;border-radius: 150px;-webkit-border-radius: 150px;-moz-border-radius: 150px;"> '
    flash("you are now logged in as %s" % login_session['username'])
    print "done!"
    return output


# User Helper Functions
def createUser(login_session):
    newUser = User(name=login_session['username'], email=login_session[
                   'email'], picture=login_session['picture'])
    session.add(newUser)
    session.commit()
    user = session.query(User).filter_by(email=login_session['email']).one()
    return user.id


def getUserInfo(user_id):
    user = session.query(User).filter_by(id=user_id).one()
    return user


def getUserID(email):
    try:
        user = session.query(User).filter_by(email=email).one()
        return user.id
    except:
        return None


# DISCONNECT - Revoke a current user's token and reset their login_session
@app.route('/gdisconnect')
def gdisconnect():
    access_token = login_session.get('access_token')
    if access_token is None:
        print 'Access Token is None'
        response = make_response(json.dumps('Current user not connected.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response
    print 'In gdisconnect access token is %s', access_token
    print 'User name is: '
    print login_session['username']
    url = 'https://accounts.google.com/o/oauth2/revoke?token=%s' % login_session['access_token']
    h = httplib2.Http()
    result = h.request(url, 'GET')[0]
    print 'result is '
    print result
    if result['status'] == '200':
        del login_session['access_token']
        del login_session['gplus_id']
        del login_session['username']
        del login_session['email']
        del login_session['picture']
        response = make_response(json.dumps('Logged Out'), 200)
        response.headers['Content-Type'] = 'application/json'
        return response
    else:
        response = make_response(json.dumps('Failed to revoke token for given user.', 400))
        response.headers['Content-Type'] = 'application/json'
        return response


# Create anti-forgery state token
@app.route('/login')
def showLogin():
    state = ''.join(random.choice(string.ascii_uppercase + string.digits)
                    for x in xrange(32))
    login_session['state'] = state
    return render_template('login.html', STATE=state)


# List of Categories
@app.route('/')
@app.route('/categories/')
def showCategories():
    categories = session.query(Category).order_by(asc(Category.name))
    return render_template('categories.html', categories=categories)


# Create new category item
@app.route('/catalog/<int:category_id>/new', methods=['GET', 'POST'])
@login_required
def newCategoryItem(category_id):
    if request.method == 'POST':
        newItem = Item(name=request.form['name'],
                       user_id=login_session['user_id'],
                       category_id=category_id,
                       description=request.form['desc'])
                       
        session.add(newItem)
        session.commit()
        flash("Item: " + request.form['name'] + " created!!")
        return redirect(url_for('catalogItems', category_id=category_id))
    else:
        return render_template('newitem.html', category_id=category_id)


# List of Category items for a Category id
@app.route('/catalog/<int:category_id>/')
@app.route('/catalog/<int:category_id>/items')
def catalogItems(category_id):
    category = session.query(Category).filter_by(id=category_id).first()
    items = session.query(Item).filter_by(category_id=category.id)
    return render_template('items.html', category=category, items=items)


# only if logged in can you edit an item
@app.route('/catalog/<int:category_id>/<int:item_id>/edit', methods=['GET', 'POST'])
@login_required
def editItem(category_id, item_id):
    editedItem = session.query(Item).filter_by(id=item_id).one()
    if login_session['user_id'] != editedItem.user_id:
        return "<script>function myFunction() {alert('You are not authorized to edit this item. Please create your own items.');}</script><body onload='myFunction()''>"
    if request.method == 'POST':
            editedItem.name = request.form['name']
            editedItem.description = request.form['desc']
            session.add(editedItem)
            session.commit()
            flash("Item: " + request.form['name'] + " edited!!")
            return redirect(url_for('catalogItems', category_id=category_id))
    else:
            return render_template('editItem.html', category_id=category_id, item_id=item_id, item=editedItem)


# Only if you are logged in can you delete an item
@app.route('/catalog/<int:category_id>/<int:item_id>/delete', methods=['GET', 'POST'])
@login_required
def deleteItem(category_id, item_id):
    itemToDelete = session.query(Item).filter_by(id=item_id).one()
    if login_session['user_id'] != itemToDelete.user_id:
        return "<script>function myFunction() {alert('You are not authorized to delete this item.');}</script><body onload='myFunction()''>"
    if request.method == 'POST':
        session.delete(itemToDelete)
        session.commit()
        flash("Item: " + itemToDelete.name + " deleted!!")
        return redirect(url_for('catalogItems', category_id=category_id))
    else:
        return render_template('deleteItem.html', item=itemToDelete)


# Returns a Json array Categorys containing their items.
@app.route('/catalog.json')
def fetchJSON():
    categories = session.query(Category).all()
    categoriesJson = [category.serialize for category in categories]
    for category in categoriesJson:
        items = session.query(Item).filter_by(category_id=category['id'])
        # Create new Key in dictionary
        category['items'] = [item.serialize for item in items]

    return jsonify(Category=categoriesJson)


if __name__ == '__main__':
    app.secret_key = 'super_secret_key'
    app.debug = True
    app.run(host='0.0.0.0', port=8000)
