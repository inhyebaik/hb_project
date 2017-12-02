from jinja2 import StrictUndefined
from flask import (Flask, render_template, redirect, request, flash, session,
                   jsonify)
from flask_debugtoolbar import DebugToolbarExtension
from flask_sqlalchemy import SQLAlchemy
from flask.ext.bcrypt import Bcrypt
from werkzeug.security import generate_password_hash, check_password_hash
from model import User, Event, ContactEvent, Contact, Template, db, connect_to_db
import random, json
from quotes import *

# SendGrid Emailing
import os, time, json, datetime, schedule, sendgrid
from sendgrid.helpers.mail import *

# Twilio Texting
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client

# Threading schedule jobs
from schedule_jobs import schedule1
import threading

app = Flask(__name__)

# Required to use Flask sessions and the debug toolbar
app.secret_key = "ABC"
app.jinja_env.undefined = StrictUndefined # raise error if you use undefined variable in Jinja2


# Source secrets and create client for Twilio
account = os.environ.get('TWILIO_TEST_ACCOUNT')
token = os.environ.get('TWILIO_TEST_TOKEN')
client = Client(account, token)

twilio_num = os.environ.get('TWILIO_NUMBER')
my_num = os.environ.get('MY_NUMBER')
my_email = os.environ.get('MY_EMAIL')
kit_email = os.environ.get('KIT_EMAIL')



@app.route('/test')
def return_template():
    user_id = session.get('user_id')
    user = User.query.filter(User.id == user_id).first()
    return render_template('homepage1.html', user=user)

########### ROUTES FOR AJAX REQUESTS ############

@app.route('/quote')
def return_quote():
    """Returns random quote from QUOTES."""
    author, quote = random_quote(QUOTES)
    return quote+"<br>"+ "-"+author


@app.route('/msg.json', methods=['POST'])
def return_msg():
    """Return random message for preselected template type"""
    # import pdb; pdb.set_trace()
    template_type = request.form.get('template_type')
    print template_type
    msg = random_message(template_type)
    print msg
    return jsonify({"message": msg})


@app.route('/contact.json', methods=['POST'])
def return_contact_info():
    contact_id = request.form.get('contact_id')
    contact = Contact.query.get(contact_id)
    return jsonify({'name': contact.name, 'email': contact.email, 'address': contact.address, 'phone': contact.phone})


def add_fb_conctacts(contacts_list):
    """If a user registers in via OAuth, add their FB friends as contacts."""
    user_id = session['user_id']
    for thing in contacts_list:
        try:
            name = thing[0]
            pic_url = thing[1]
            c = Contact(name=name, pic_url=pic_url, user_id=user_id)
            db.session.add(c)
            db.session.commit()
            print "{} add to DB for user_id={}".format(name, user_id)
        except:
            pass


@app.route('/fb_register', methods=['POST'])
def fb_register():
    """Registers user via FB."""
    print "hit the route /fb_register!"
    # things from FB API request 
    fname = request.form.get('fname')
    lname = request.form.get('lname')
    fb_uid = request.form.get('fb_uid')
    email = request.form.get('email')
    pic_url = request.form.get('pic_url')
    contacts_list = json.loads(request.form.get('contacts_list'))

    password = request.form.get('fb_uid')
    hashed_value = generate_password_hash(password)

    db_user = User.query.filter(User.email == email).first()

    # If user exists in DB, add them to session (log in), return db_user.id:
    if db_user:
        print "Existing user!!!!"
        session['user_id'] = db_user.id
        return jsonify({'user_id':db_user.id, 'result': 'Existing user!'})
    else:
        # Add new_user to database; return new_user.id
        print "email doesn't exist--> New user being adding to DB and logging in"
        new_user = User(email=email, password=hashed_value, fname=fname, lname=lname, fb_uid=fb_uid, pic_url=pic_url)
        db.session.add(new_user)
        db.session.commit()
        print "new user added to DB"
        session['user_id'] = new_user.id
        print "user added to session"
        if contacts_list:
            print "about to add FB contacts"
            add_fb_conctacts(contacts_list)
        return jsonify({'user_id':new_user.id, 'result': 'Newly registered user!'})


# END JSON ROUTES

@app.route('/')
def index():
    """Homepage."""
    user_id = session.get('user_id')
    user = User.query.filter(User.id == user_id).first()
    if user:
        return render_template("homepage3.html", user=user)
    else:
        return render_template("not_logged_in_index.html")


@app.route('/users')
def user_list():
    """Show list of users."""
    users = User.query.all()
    user_id = session.get('user_id')
    user = User.query.filter(User.id == user_id).first()
    return render_template("user_list.html", users=users, user=user)


@app.route('/logout')
def log_out():
    """Log user out; clear out session; confirm log out; redirect to homepage"""
    del session['user_id']
    flash("You have successfully logged out!")
    return redirect("/")


@app.route('/register_login')
def register_form():
    """Prompts user to register/sign in"""

    return render_template("register_login_form.html")


@app.route('/register', methods=['POST'])
def register_process():
    """Adds new user to DB; adds to session"""
    # Grab information from registration form
    email = request.form.get('email')
    password = request.form.get('password')
    hashed_value = generate_password_hash(password)
    fname = request.form.get('fname')
    lname = request.form.get('lname')
    phone = request.form.get('phone')
    # Fetch that user from DB as object
    db_user = User.query.filter(User.email == email).first()

    # If that user exists in DB:
    if db_user:
        # Alert the email is already in use; prompt them to login instead
        flash("Email already exists in database -- Please try logging in")
        return redirect('/register_login')
    else:
        # Register new user; add to DB; log them in; save user_id to session
        new_user = User(email=email, password=hashed_value, fname=fname, lname=lname,
                        phone=phone)
        db.session.add(new_user)
        db.session.commit()
        flash("You're now added as a new user! Welcome!")
        session['user_id'] = new_user.id
        url = '/users/{}'.format(new_user.id)
        # Redirect to the user's info page
        return redirect(url)


@app.route('/login', methods=['POST'])
def login_process():
    """Logs user in; adds to session"""
    # Gets information from login input form
    email = request.form.get('login_email')
    login_password = request.form.get('login_password')
    # Fetch that user from DB as object
    print email, login_password
    db_user = User.query.filter(User.email == email).first()
    print db_user
    # If that user exists in DB:
    if db_user:
        # Verify password; redirect to their profile
        password = db_user.password
        if check_password_hash(password, login_password):
            session['user_id'] = db_user.id # add user_id to the session
            flash("You have successfully logged in!")
            url = '/users/{}'.format(db_user.id)
            return redirect(url)
        else:
            # If password doesn't match, redirect to register/login
            flash("Wrong credentials -- Try again")
            return redirect('/register_login')
    else:
        # Alert if email doesn't exist; prompt and redirect to register/login
        flash("Email does not exist in database: please register")
        return redirect('/')


@app.route('/users/<user_id>')
def user_profile(user_id):
    """Shows specific user's info; all of their events and contacts."""
    user = User.query.get(user_id)
    contacts = Contact.query.filter(Contact.user_id == user_id).all()
    upcoming_events = Event.query.order_by(Event.date.asc()).limit(5)
    return render_template("user_profile.html", user=user, contacts=contacts, upcoming_events=upcoming_events)


@app.route('/user_profile')
def user_profile1():
    """New user profile / dashboard."""
    user_id = session.get("user_id")
    if user_id:
        user = User.query.get(user_id)
        contacts = Contact.query.filter(Contact.user_id == user_id).all()
        return render_template('user_profile1.html', user=user, contacts=contacts)
    else:
        flash("You must log in or register to add events")
        return redirect("/")


@app.route('/add_event')
def add_event():
    """Let logged in users go to the new event form."""
    user_id = session.get("user_id")
    if user_id:
        user = User.query.get(user_id)
        return render_template("event_form.html", user=user)
    else:
        flash("You must log in or register to add events")
        return redirect("/")


@app.route('/add_event', methods=['POST'])
def handle_event_form():
    """Validates and adds new event and template to DB."""
    # Need to add the contact and template before creating an event

    # add contact
    name = request.form.get('contact_name')
    email = request.form.get('contact_email')
    phone = request.form.get('contact_phone')
    address = request.form.get('contact_address')
    user_id = session.get("user_id")
    new_contact = Contact(name=name, email=email, phone=phone, address=address, user_id=user_id)
    db.session.add(new_contact)
    db.session.commit()

    # get inputs from form for template text
    greet = request.form.get('greet')
    sign_off = request.form.get('sign_off')
    body = request.form.get('body')
    user_fname = User.query.get(user_id).fname
    template_text = "{} {}, \n{} \n{},\n{}".format(greet, name.encode('utf-8'), body, sign_off,
                                                   user_fname)

    # add template
    template_name = request.form.get('template_name')
    new_template = Template(name=template_name, text=template_text)
    db.session.add(new_template)
    db.session.commit()

    # add event
    contact_id = new_contact.id
    date = request.form.get('date')
    print date
    new_event = Event(contact_id=contact_id, template_id=new_template.id, date=date)
    db.session.add(new_event)
    db.session.commit()

    # add ContactEvent association
    ce = ContactEvent(contact_id=contact_id, event_id=new_event.id)
    db.session.add(ce)
    db.session.commit()

    # redirect to user profile
    flash("You have successfully added a new event for {}!".format(name))
    url = '/users/{}'.format(user_id)
    return redirect(url)


@app.route('/edit_event/<event_id>')
def show_event(event_id):
    """Show specific event to view or modify"""

    user_id = session.get("user_id") # make sure the user is logged in
    if user_id:
        user = User.query.get(user_id)
        event = Event.query.get(event_id)
        return render_template("edit_event.html", event=event, user=user)
    else:
        flash("You must log in or register to modify events")
        return redirect("/")



@app.route('/handle_edits', methods=['POST'])
def modify_db():
    """Allow user to change event and template that will go into DB."""

    # get user and event primary keys we are modifying for
    user_id = session.get("user_id")
    event_id = int(request.form.get('event_id'))

    # get the user, event, and contact objects we are modifying for
    user = User.query.get(user_id)
    event = Event.query.get(event_id)
    contact = Contact.query.filter(Contact.id == event.contact_id).one()

    # update contact, event, template objects in the DB
    contact.name = request.form.get('contact_name')
    event.template.text = request.form.get('template_text')
    contact.email = request.form.get('contact_email')
    contact.phone = request.form.get('contact_phone')
    contact.address = request.form.get('contact_address')
    event.date = request.form.get('date')
    db.session.commit()
    flash("Message updated successfully. We will remind you the day before (on {}/{}/{})".format(event.date.month, event.date.day-1, event.date.year))
    # redirect user to their profile
    url = '/users/{}'.format(user_id)
    return redirect(url)


@app.route('/remove_event', methods=['POST'])
def remove_event():
    """Delete event and template (but not the contact) from DB."""
 
    user_id = session.get("user_id")
    if user_id:
        # get event_id from hidden input;  
        event_id = request.form.get('event_id')
        template_id = Event.query.get(event_id).template_id
        # delete ContactEvent association table link 
        ContactEvent.query.filter(ContactEvent.event_id == event_id).delete()
        # and then delete the Event
        Event.query.filter(Event.id == event_id).delete()
        Template.query.filter(Template.id == template_id).delete()
        db.session.commit()
        flash("You have successfully deleted this event")
        url = '/users/{}'.format(user_id)
        return redirect(url)
    else:
        flash("You must log in or register to remove events")
        return redirect("/")


@app.route('/remove_contact/<contact_id>')
def confirm(contact_id):
    """Confirmation page to delete contact (and their events,templates) from DB."""
    user_id = session.get("user_id")
    if user_id:
        contact = Contact.query.get(contact_id)
        return render_template('remove_contact.html', contact=contact)
    else:
        flash("You must log in or register to remove contacts")
        return redirect("/")


    
@app.route('/remove_contact', methods=['POST'])
def remove_contact():
    """Delete contact (and their events, and templates) from DB."""
    user_id = session.get("user_id")
    contact_id = request.form.get('contact_id')
    if user_id:
        # delete the ContactEvent association 
        ContactEvent.query.filter(ContactEvent.contact_id == contact_id).delete()
        #### delete their Events and their templates    
        events = Event.query.filter(Event.contact_id == contact_id).all()
        # get the template ids for all of the events for that one contact
        template_ids = []
        for event in events:
            template_ids.append(event.template_id)
        # delete the events
        Event.query.filter(Event.contact_id == contact_id).delete()
        db.session.commit()
        # delete the templates
        for template_id in template_ids:
            Template.query.filter(Template.id == template_id).delete()
            db.session.commit()
        # delete the contact
        Contact.query.filter(Contact.id == contact_id).delete()
        db.session.commit()
        flash("You have successfully deleted this contact")
        user_id = session.get('user_id')
        url = '/users/{}'.format(user_id)
        return redirect(url)
    else:
        flash("You must log in or register to remove contacts")
        return redirect("/")



####### specifically given a contact #################

@app.route('/add_event/<contact_id>')
def add_event_for_contact(contact_id):
    """Let logged in users add an event given a contact."""
    user_id = session.get("user_id")
    if user_id:
        user = User.query.get(user_id)
        contact = Contact.query.get(contact_id)
        return render_template("event_for_contact.html", user=user, contact=contact)
    else:
        flash("You must log in or register to add events")
        return redirect("/")



@app.route('/handle_new_event_for_contact', methods=['POST'])
def handle_new_event_for_contact():
    """Handle new event for contact form; updates DB"""
    # Get user object
    user_id = session.get('user_id')
    user = User.query.get(user_id)
    # Get contact object (hidden input from event_for_contact.html)
    contact_id = request.form.get('contact_id')
    contact = Contact.query.get(contact_id)
    # get inputs from form for template text
    greet = request.form.get('greet')
    sign_off = request.form.get('sign_off')
    body = request.form.get('body')
    user_fname = user.fname
    template_text = "{} {}, \n{} \n{},\n{}".format(greet, contact.name.encode('utf-8'), body, sign_off,
                                                   user_fname)
    # add template
    template_name = request.form.get('template_name')
    new_template = Template(name=template_name, text=template_text)
    db.session.add(new_template)
    db.session.commit()
    # add event
    date = request.form.get('date')
    new_event = Event(contact_id=contact_id, template_id=new_template.id, date=date)
    db.session.add(new_event)
    db.session.commit()
    # add ContactEvent association
    ce = ContactEvent(contact_id=contact_id, event_id=new_event.id)
    db.session.add(ce)
    db.session.commit()
    # redirect to edit_event page
    flash("You have successfully added a new event for {}!".format(contact.name.encode('utf-8')))
    url = '/users/{}'.format(user.id)
    return redirect(url)


@app.route('/edit_profile')
def edit_profile():
    user_id = session.get('user_id')
    if user_id:
        user = User.query.get(user_id)
        return render_template('edit_profile.html', user=user)
    else:
        flash("You must log in or register to edit your profile")
        return redirect("/")


@app.route('/e_profile', methods=['POST'])
def handle_profile_edits():
    user_id = session.get('user_id')
    fname = request.form.get('fname')
    lname = request.form.get('lname')
    email = request.form.get('email')
    phone = request.form.get('phone')
    if user_id:
        user = User.query.get(user_id)
        user.fname = fname
        user.lname = lname
        user.email = user.email
        user.phone = phone
        db.session.commit()
        flash("Your information has been updated successfully.")
        url = '/users/{}'.format(user_id)
        return redirect(url)
    else:
        flash("You must log in or register to add events")
        return redirect("/")


@app.route('/edit_contact/<contact_id>')
def edit_contact(contact_id):
    user_id = session.get('user_id')
    if user_id:
        user = User.query.get(user_id)
        contact = Contact.query.get(contact_id)
        return render_template('edit_contact.html', contact=contact)
    else:
        flash("You must log in or register to add events")
        return redirect("/")


@app.route('/edit_contact/<contact_id>', methods=['POST'])
def edit_contact_db(contact_id):
    """Updates DB for contact's information // edit_contact.html form"""
    # contact_id = request.form.get(contact_id)
    name = request.form.get('name')
    email = request.form.get('email')
    phone = request.form.get('phone')
    address = request.form.get('address')
    # Fetch contact from DB; update DB
    contact = Contact.query.get(contact_id)
    contact.name, contact.email, contact.phone, contact.address = name, email, phone, address
    db.session.commit()
    flash("{}'s information has been updated!".format(contact.name))
    user_id = session.get('user_id')
    url = '/users/{}'.format(user_id)
    return redirect(url)


### TEXTING REMINDER WITH TWILIO ###
def text_reminder(event):
    """Text reminder to user of an event; asks if they want to update msg"""
    user_phone = event.contacts[0].user.phone
    user_fname = event.contacts[0].user.fname
    c_name = event.contacts[0].name
    # Send an SMS
    my_msg = "\n\n\nHello {}, your event's coming up tomorrow for {}.\n\n--------\n\nYour message \
currently is:\n'{}'\n\n--------\n\nIf you'd like to update this message, please \
reply with your new message (in one SMS response. Please add 'event_id={}' in your response)".format(user_fname, c_name, event.template.text, event.id)
    message = client.messages.create(to=user_phone, from_=twilio_num, body=my_msg)
    print "MESSAGE SENT to {}".format(user_phone)



##### Twilio Incoming Messages Handler, using ngrok 5000 ########

@app.route("/sms", methods=['GET', 'POST'])
def handle_reminder_response():
    """Handle user response to reminder"""
    to_number = request.values.get('To') # Keep in Touch's phone
    from_number = request.values.get('From', None) # user's phone
    user_response = request.values.get('Body')
    # Fetch user from DB to update event template text
    user = User.query.filter(User.phone == from_number).one()
    user_fname = user.fname
    event_id = None
    # Get tomorrow's date to fetch the events, formatted to match DB date fields
    t = datetime.datetime.now()
    today = datetime.datetime(t.year, t.month, t.day, 0, 0)
    # tmrw = datetime.datetime(t.year, t.month, t.day+1, 0, 0)

    if "event_id" in user_response.lower():
        eindex = user_response.index("event_id")
        # Get event_id from incoming text (recipients were instructed to end reply with 'event_id=XX')
        event_id = int(user_response[(eindex + len("event_id=")):])
        event = Event.query.get(event_id)
        new_text = user_response[:eindex].rstrip()
        # Update database with new event template text for their contact
        event.template.text = new_text
        db.session.commit()
        # Send confirmation text of the change
        message = "Thanks, {}! Your new message will be updated in the database as: '{}'".format(user_fname, event.template.text)
        resp = MessagingResponse()
        resp.message(body=message)
        return str(resp)
    else:
        # Reply to user, prompting to end new message with "event_id=XX"
        for contact in user.contacts:
            for event in contact.events:
                if event.date == tmrw:
                    # Will unfortunately have to send this to every event tomorrow
                    my_msg = "You didn't add 'event_id={id}' in your response. Please text us the same message with the 'event_id={id}' at the end".format(id=event.id)
                    message = client.messages.create(to=from_number, from_=to_number, body=my_msg)



###############################################################
if __name__ == "__main__": 
    app.debug = True
    app.jinja_env.auto_reload = app.debug  # make sure templates, etc. are not cached in debug mode
    connect_to_db(app)
    DebugToolbarExtension(app) # Use the DebugToolbar
    
    def run_app():
        app.run(port=5000, host='0.0.0.0')

    # def run_jobs(app):
    #     # import pdb; pdb.set_trace()
    #     sched = threading.Thread(name='schedule1', target=schedule1)
    #     app = threading.Thread(name='app', target=run_app)
    #     sched.start()
    #     app.start()
    run_jobs(app)
    run_app()

    
    
    