# -*- coding: utf-8 -*-
"""
Created on Thu Nov 23 18:22:53 2023

@author: skhan2
"""
from flask_socketio import SocketIO, emit
import time  # Used for simulating processing time


from flask import Flask, request, render_template, jsonify, send_file, session
from functools import wraps
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker
from flask import Flask, render_template, redirect, request, url_for, flash
from werkzeug.utils import secure_filename, safe_join
from tqdm import tqdm
from flask_socketio import SocketIO
import os
from ORM import MaskTable, ComponentTable, MappingJSON
from DB_Operations import DB_Operations as CRUD
import SingleAddressParser_Module as SAP
from werkzeug.security import generate_password_hash, check_password_hash
import hashlib
import Address_Parser__Module as BAP
from flask_cors import CORS
import json
import threading
from datetime import datetime
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from LoginORM import User, UserRole
from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileRequired
from wtforms import SubmitField
from wtforms import StringField, PasswordField, SubmitField
from wtforms.validators import InputRequired, Length
from flask_socketio import SocketIO, emit
import logging
import bcrypt
import base64

logging.basicConfig(level=logging.DEBUG)

current_time = datetime.now()
app = Flask(__name__, template_folder='templates')
engine = create_engine('sqlite:///KnowledgeBase_Test.db')
engine2 = create_engine('sqlite:///User_Auth.db', echo=True)
Session = sessionmaker(bind=engine)
DBSession=sessionmaker(bind=engine2)
app.config['SECRET_KEY'] = 'secret!'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # for 16MB max-size

socketio = SocketIO(app)
CORS(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'


class LoginForm(FlaskForm):
    username = StringField('Username', validators=[InputRequired(), Length(min=4, max=30)])
    password = PasswordField('Password', validators=[InputRequired()])
    submit = SubmitField('Login')

class RegisterForm(FlaskForm):
    username = StringField('Username', validators=[InputRequired(), Length(min=4, max=30)])
    password = PasswordField('Password', validators=[InputRequired()])
    submit = SubmitField('Register')

class BatchUploadForm(FlaskForm):
    file = FileField('Upload File', validators=[FileRequired()])
    submit = SubmitField('Process File')

def hash_password(password):
    """ Hash a password using bcrypt """
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode(), salt)

@app.route('/login', methods=['GET', 'POST'])
def login(): 
    form = LoginForm()  # Ensure this matches the name of your form class
    if form.validate_on_submit():
            sessions = DBSession()
            username = request.form['username']
            password = request.form['password']  
            user = sessions.query(User).filter_by(UserName=username).first()
            # userTable = sessions.query(User).all()
            if user and bcrypt.checkpw(password.encode(), user.Password): 
                role_name = user.role.RoleName
                
                session["user_id"]=username
                session["role"]= role_name
                session['status'] = user.Status
                print("\n\n\n",session['status'],"\n", user.Status,"\n\n\n")
                return redirect(url_for('SingleLineAddressParser')) 
            
           # Remember, in real apps, don't use plain text for passwords
           
            else:
                session.clear()
                flash('Invalid username or password')
    return render_template('login.html', form=form)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


def requires_role(role):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_id' not in session:
                flash('You need to be logged in to view this page.')
                return redirect(url_for('login'))
            user = session['user_id']
            role= session["role"]
            if not user or role != role:
                flash('You do not have the required permissions to view this page.')
                return redirect(url_for('SingleLineAddressParser'))  # Or some other appropriate redirect
            return f(*args, **kwargs)
        return decorated_function
    return decorator



@app.route('/logout', methods=["GET", "POST"])
def logout():
    flash('You have been logged out!')
    session.clear()
    return redirect(url_for('login'))






@app.route('/', methods=["GET", "POST"])
@requires_role('Admin')
def SingleLineAddressParser():
    result = {}
    form = BatchUploadForm()
    try:
        
        if request.method == 'POST':
            address = request.form['address']
            convert = SAP.Address_Parser(address, 'Initials', address)
            if convert[4]:
                result = convert[0]
                result['Parsed_By'] = 'Rule Based'
            else:
                result = convert[0]
                result['Parsed_By'] = 'Active Learning'
            print(result)
            return jsonify(result=result)
    except:
        return render_template('index.html', result=result, form=form)
            
    return render_template('index.html', result=result, form=form)


@app.route("/forceException", methods=["GET", "POST"])
def forceException():
    response = {'result': False}
    global download_except_path  # Make sure to use the global variable
    if request.method == "POST":
        address = request.form["address"]
        convert = SAP.throwException(address, "initials")
        if convert is not None:  # Check if the return value is not None
            response['result'] = True
            download_except_path = convert  # Assign the returned file path
        print(convert)
        
    return jsonify(response=response, download_url="/download_except")

@app.route('/download_except')
def download_except_file():  # Ensure this function name is unique
    global download_except_path
    if download_except_path is None:
        return jsonify({'error': 'No file to download'}), 404
    try:
        return send_file(download_except_path, as_attachment=True)
    except FileNotFoundError:
        return jsonify({'error': 'File not found'}), 404


task_results = {}
def process_file_in_background(file, filename):
    convert = BAP.Address_Parser(file, "update_progress")
    task_results[filename] = {
        "result": convert[1] if convert[0] else None,
        "metrics": {'metrics': convert[1]} if convert[0] else None,
        "output_file_path": convert[2] if convert[0] else None
    }
    
    with open("temp_file.json", "w", encoding = "utf8") as file:
        json.dump(task_results, file, indent=4)
        
        
    

@app.route('/Batch_Parser', methods=["GET", "POST"])
def BatchParser():
    form = BatchUploadForm()
    print("Processing starsted: ", flush=True)
    
    if form.validate_on_submit():
        global task_results

        file = form.file.data
        filename = secure_filename(file.filename)
        file_path = os.path.join('File Uploads', filename)
        file.save(file_path)

        thread = threading.Thread(target=process_file_in_background, args=(file_path, filename))
        thread.run()
       
        return jsonify(status="Processing started", status_check_url='/check_status/' + filename, download_url='/download_output/' + filename)

    return jsonify(status="Upload a file")

@app.route('/check_status/<filename>', methods=["GET", "POST"])
def check_status(filename):
    print("sdksdksd") 
    task_results=dict()
    try:
            
        with open("temp_file.json", "r", encoding="utf8") as file:
        # Load the JSON content from the file into a Python dictionary
            task_results = json.load(file)
        if task_results[filename]["result"] is not None:
            return jsonify(result=task_results[filename]["result"], metrics=task_results[filename]["metrics"])
        else:
            return jsonify(status="Still processing"), 202
    except:
        pass
# else:
    #     return jsonify(error=str(task_results)), 404

@app.route('/download_output/<filename>')
def download_file(filename):
    task_results=dict()
    with open("temp_file.json", "r", encoding="utf8") as file:
    # Load the JSON content from the file into a Python dictionary
        task_results = json.load(file)

    if filename in task_results and task_results[filename]["output_file_path"] is not None:
        try:
            return send_file(task_results[filename]["output_file_path"], as_attachment=True)
        except FileNotFoundError:
            return jsonify({'error': 'File not found'}), 404
    else:
        return jsonify({'error': 'Result not ready or file not found'}), 404

@app.route('/AddressComponents_dropdown', methods=['GET'])
def get_address_components():
    try:
        session = Session()
        components = session.query(ComponentTable.description).all()
        options = [component[0] for component in components]
        print(options)
        session.close()
        return jsonify(options)
    except Exception as e:
        print(f"Error occurred: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/check-mask-existence', methods=['POST'])
def check_mask_existence():
    session = Session()
    data = request.get_json()
    mask = data.get('mask')
    mask_record = session.query(MaskTable).filter_by(mask=mask).first()
    return jsonify({'exists': mask_record is not None})


@app.route('/MapCreationForm-Data',methods=["GET","POST"])
def MapCreationForm():
    session = Session()
    database_url = 'sqlite:///KnowledgeBase_Test.db'
    engine = create_engine(database_url)
    result={}
    mapdata = request.get_json()
    print("\nReceived Map Data:",mapdata)
    keys = list(mapdata.keys())
    Vdbs = {k: mapdata[k] for k in keys[:10]}
    Vdbs["Approved By"] = Vdbs["Approved By"] + " at " + str(current_time)
    Kbs = {k: mapdata[k] for k in keys[10:]}
    print("\n\nValidation Data Base: ",Vdbs)
    print("\n\nKnowledge Base: ",Kbs)
    if Vdbs["Address Approved?"] == "Yes":
        CRUD.add_data(engine,Kbs)
        print("Approved: Yes")
        with open("Validation_DB.txt", 'r+') as file:
            try:
                existing_data = json.load(file)
            except json.JSONDecodeError:
                existing_data = []
            existing_data.append(Vdbs)
            file.seek(0)
            json.dump(existing_data, file, indent=4)
            file.truncate()
    else:
        print("Approved: No")
        Vdbs["Rejected By"] = Vdbs["Approved By"]
        del Vdbs["Approved By"]
        print(Vdbs)
        with open("ADDR_Rejection_DB.txt", "r+") as file:
            try:
                existing_data = json.load(file)
            except json.JSONDecodeError:
                existing_data = []
            existing_data.append(Vdbs)
            file.seek(0)
            json.dump(existing_data, file, indent=4)
            file.truncate()
        
    return jsonify({"status":"success","message":"Form Data Received"})



@app.route('/UserDefinedComponents', methods=["GET","POST"])
def UD_Components():
    result= {}
    database_url = 'sqlite:///KnowledgeBase_Test.db'
    Database_schema = CRUD(database_url)
    if request.method == "POST":
        component_data = Database_schema.get_Component_data()
        for row in component_data:
            component = row.component
            Component_description = row.description
            result[component] = Component_description
        print(result)
        return jsonify(result=result)
    elif request.method == "GET":
        # Handle GET request (if needed)
        return jsonify(message="GET request received for UserDefinedComponents")
    return jsonify(result=result)

@app.route("/add_new_component", methods=["POST"])
def add_new_component():
    result = {}
    try:
        if request.method == "POST":
            new_component = request.form.get('newComponent')  # Get the new component from the form data
            print("New Component: ",new_component)
            new_description = request.form.get('newDescription')  # Get the new description from the form data
            print("New Description: ",new_description)
            session = Session()
    
            try:
                new_ud_component = ComponentTable(component=new_component, description=new_description)
                session.add(new_ud_component)
                session.commit()
    
    
                result['message'] = 'New component added successfully'
                session.close()
    
            except Exception as e:
                session.rollback()
                session.close()
                print("Error occurred:", str(e))
                return jsonify(result={'error': f'Error: {str(e)}'})
        return jsonify(result={'success': True, 'message': 'New component added successfully'})
    except Exception as e:
        return jsonify(result={'error': str(e)})

    return jsonify(result=result)

@app.route('/save_changes', methods=['POST'])
def Edit_Components():
    if request.method == 'POST':
        received_data = request.json['components']  # Get combined old and modified data
        print("Received data on server:", received_data)
        
        session = Session()
        try:
            print("Received data:", received_data)
            # Process and update Component Table using SQLAlchemy ORM
            for component_data in received_data:
                # Identify the old component
                old_component = session.query(ComponentTable).filter_by(
                    component=component_data['oldComponent'],
                    description=component_data['oldDescription']
                ).first()

                if old_component:
                    # Update the old component with new values
                    old_component.component = component_data['newComponent']
                    old_component.description = component_data['newDescription']
                    session.commit()
                old_mappings = session.query(MappingJSON).filter_by(
                    component_index=component_data['oldComponent']
                ).all()

                for old_mapping in old_mappings:
                    old_mapping.component_index = component_data['newComponent']
                    session.commit()
            session.commit()
            session.close()
            
            return jsonify({'message': 'Changes saved successfully'})

        except Exception as e:
            session.rollback()
            session.close()
            print("Error occurred:", str(e))
            return jsonify({'message': f'Error: {str(e)}'})

@app.route("/get_mask_count", methods=["GET"])
def get_mask_count():
    result = {}
    if request.method == "GET":
        component = request.args.get('component')  # Get the component from the query parameters
        session = Session()
        print('Component about to be deleted', component)

        try:
            # Query the count of associated masks
            mask_entries = session.query(MappingJSON.mask_index).filter_by(component_index=component).distinct().all()
            # mask_count = session.query(func.count(MappingJSON.mask_index)).filter_by(component_index=component).scalar()

            total_masks = 0
            for row in mask_entries:
                mask_index = row.mask_index
                masks = session.query(func.count(MaskTable.mask)).filter_by(mask=mask_index).scalar()
                total_masks += masks

            result['maskCount'] = total_masks
            print(result)
            session.close()

        except Exception as e:
            session.close()
            print("Error occurred:", str(e))
            return jsonify(result={'error': f'Error: {str(e)}'})

    return jsonify(result=result)



@app.route("/delete_record", methods=["POST"])
def delete_component():
    # result = {}
    if request.method == "POST":
        component = request.form['component']  # Get the component to be deleted
        print("Component to delete",component)
        session = Session()
        
        try:
            # Delete from MappingJSON and get associated MaskTable entries
            mappings_to_delete = session.query(MappingJSON).filter_by(component_index=component).all()
            mask_entries_to_delete = []
            for mapping in mappings_to_delete:
                mask_entries = session.query(MaskTable).filter_by(mask=mapping.mask_index).all()
                mask_entries_to_delete.extend(mask_entries)
                session.delete(mapping)

            # Delete from ComponentTable
            component_to_delete = session.query(ComponentTable).filter_by(component=component).first()
            if component_to_delete:
                session.delete(component_to_delete)

            # Delete from MaskTable
            for mask_entry in mask_entries_to_delete:
                session.delete(mask_entry)

            session.commit()
            session.close()

            return jsonify(result={'message': f'Record for component {component} deleted successfully'})
        except Exception as e:
            session.rollback()
            session.close()
            print("Error occurred:", str(e))
            return jsonify(result={'message': f'Error: {str(e)}'})

@app.route('/authentication')
@requires_role('Admin')
def authentication_page():
    session = DBSession()
    try:
        users = session.query(User).filter(User.Role != "Admin").all()
        # print("Fetched Users: ", users)
        # roles = session.query(UserRole).all()
        roles = session.query(UserRole).filter(UserRole.RoleName != "Admin").all()

        # print("Fetched Roles: ", roles)  # Debugging line


        user_data = [
            {
                'id': user.id, 
                'fullName': user.FullName, 
                'userName': user.UserName, 
                'email': user.Email, 
                'password' : "********",
                'Active' : user.Status,
                'role': user.role.RoleName  # Assuming a relationship attribute
                # 'status': 'Active' if user.isActive else 'Inactive'  # Assuming an isActive field
            } for user in users
        ]
        role_data = [role.RoleName for role in roles]
        # print("role_data", role_data)
        # print("user_data", user_data)
        return jsonify({'users': user_data, 'roles': role_data})
    except Exception as e:
        print("Error: ", e)
        return jsonify({'users': [], 'roles': []})
    finally:
        session.close()

@app.route('/CRUDUser', methods=["GET", "POST"])
@requires_role('Admin')
def CRUDUser():
    sessions = DBSession() 
    users = sessions.query(User).all()
    sessions.close()
    # print(users)
    return render_template('index.html', users=users)


@app.route('/save_User/<int:user_id>', methods=['POST'])
def edit_user(user_id):
    session = DBSession()
    print("User ID", user_id)
    try:
        user = session.query(User).get(user_id)  # Find the user by ID
        print("Users: ", user)
        UserDetails = request.get_json()
        print("\n\nUserDetails: ", UserDetails, "\n\n")

        if user:
            # Update user details
            user.FullName = UserDetails.get('FullName')
            user.UserName = UserDetails.get('UserName')
            user.Email = UserDetails.get('Email')
            user.Role = UserDetails.get('Role_id')
            user.Status = UserDetails.get('Status')

            session.commit()

        return jsonify({"message": "User updated successfully"}), 200
    except Exception as e:
        session.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()

@app.route('/create_user', methods=['POST'])
def create_user():
    session = DBSession()
    try:
        UserDetails = request.get_json()
        print("create_user Details: ", UserDetails)
        user = session.query(User).get(UserDetails["UserName"])  # Find the user by ID
        print("user: ",user)
        # Create a new user instance
        new_user = User()
        new_user.FullName = UserDetails.get('FullName')
        new_user.UserName = UserDetails.get('UserName')
        new_user.Email = UserDetails.get('Email')
        
        hashed_password = hash_password(UserDetails.get('Password'))
        new_user.Password = hashed_password

        new_user.Role = UserDetails.get('Role_id')
        new_user.Status = UserDetails.get('Status')
        print("New User Rady to Add: ",new_user)
        # Add the new user to the session and commit
        session.add(new_user)
        session.commit()

        return jsonify({"message": "User updated successfully"}), 200
    except Exception as e:
        session.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()

@app.route('/delete_User/<int:user_id>', methods=['POST'])
def delete_user(user_id):
    session = DBSession()
    try:
        user = session.query(User).get(user_id)  # Find the user by ID
        if user:
            session.delete(user)  # Delete the user
            session.commit()  # Commit the changes

        return redirect(url_for('/authentication'))
    except Exception as e:
        session.rollback()
        return str(e)
    finally:
        session.close()

    
    
if __name__ == '__main__':
    
    app.run(port=8080, debug=True)

