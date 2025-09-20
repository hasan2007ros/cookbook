from flask import Flask, render_template, request, redirect, url_for, session, flash
import sqlite3
import hashlib
import os, json, uuid, glob, random
from werkzeug.utils import secure_filename

# ---------------- App setup ----------------
app = Flask(__name__, static_folder='static', template_folder='templates')
app.secret_key = 'cookbook-nea-temporary-placeholder-key-i-guess'

# Uploads config
app.config["UPLOAD_FOLDER"] = os.path.join("static", "uploads")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif"}
app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024  # 4 MB max
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


# ---------------- Schema bootstrap ----------------
def ensure_schema():
    con = sqlite3.connect("cookbook.db")
    cur = con.cursor()

    # Users table (with admin flag + profile/banner images)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            age INTEGER,
            email TEXT UNIQUE NOT NULL,
            occupation TEXT,
            dish_choice TEXT,
            diets TEXT,
            bio TEXT,
            password_hash TEXT NOT NULL,
            is_admin INTEGER DEFAULT 0,
            banner_filename TEXT,
            profile_pic_filename TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Recipes table (with rating)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS recipes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            recipe_name TEXT NOT NULL,
            recipe_type TEXT NOT NULL,
            ingredients TEXT NOT NULL,   -- JSON list string
            prep_time INTEGER NOT NULL,
            instructions TEXT NOT NULL,
            image_filename TEXT,         -- file name in /static/uploads
            description TEXT,            -- AI-generated description
            rating INTEGER DEFAULT 0,    -- overall score (yum - tomato)
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    # Votes table (tracks who voted what)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS recipe_votes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            recipe_id INTEGER NOT NULL,
            vote INTEGER NOT NULL,       -- 1 = yum, -1 = tomato
            UNIQUE(user_id, recipe_id),
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (recipe_id) REFERENCES recipes(id)
        )
    """)

    con.commit()
    con.close()

ensure_schema()


# ---------------- AI-style description generator ----------------
def generate_description(recipe_name, ingredients, recipe_type, prep_time):
    intros = [
        f"{recipe_name} is a tasty {recipe_type.lower()} that’s always a favourite.",
        f"Everyone loves {recipe_name}, a classic {recipe_type.lower()} with rich flavour.",
        f"{recipe_name} is the perfect {recipe_type.lower()} for family and friends."
    ]
    bodies = [
        "It combines simple ingredients to create something special.",
        "The result is a dish that feels both comforting and exciting.",
        "This recipe balances flavour and ease of preparation perfectly."
    ]
    ingredient_hint = ""
    if ingredients:
        ingredient_hint = f" Key ingredients include {', '.join(ingredients[:3])}."
    time_hint = f" It can be made in just {prep_time} minutes."

    return f"{random.choice(intros)}{ingredient_hint} {random.choice(bodies)}{time_hint}"


# ---------------- Routes ----------------
@app.route('/')
def home():
    conn = sqlite3.connect('cookbook.db')
    c = conn.cursor()

    # Grab top 3 recipes by rating, break ties with most recent
    c.execute("""
        SELECT id, recipe_name, image_filename, rating
        FROM recipes
        ORDER BY rating DESC, created_at DESC
        LIMIT 3
    """)
    top_recipes = [
        {
            "id": row[0],
            "name": row[1],
            "image": row[2] if row[2] else "default-recipe.jpg",
            "rating": row[3] if row[3] is not None else 0
        }
        for row in c.fetchall()
    ]
    conn.close()

    return render_template('home.html', top_recipes=top_recipes)


# -------- Register --------
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form.get('name')
        age = request.form.get('age')
        email = request.form.get('email')
        password = request.form.get('password')
        occupation = request.form.get('occupation')
        dish_choice = request.form.get('dish-choice')
        diets = request.form.getlist('diet[]')
        bio = request.form.get('bio')

        if not all([name, age, email, password]):
            flash("Please fill in all required fields.")
            return redirect(url_for('register'))

        password_hash = hashlib.sha256(password.encode()).hexdigest()
        diet_string = ', '.join(diets)

        try:
            conn = sqlite3.connect('cookbook.db')
            c = conn.cursor()
            c.execute('''
                INSERT INTO users (name, age, email, occupation, dish_choice, diets, bio, password_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (name, age, email, occupation, dish_choice, diet_string, bio, password_hash))
            conn.commit()
            conn.close()
            flash("Registration successful! Please log in.")
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash("That email is already registered.")
            return redirect(url_for('register'))
        except Exception as e:
            flash(f"An error occurred: {str(e)}")
            return redirect(url_for('register'))

    return render_template('register.html')


# -------- Login / Logout --------
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password_hash = hashlib.sha256(request.form['password'].encode()).hexdigest()

        conn = sqlite3.connect('cookbook.db')
        c = conn.cursor()
        c.execute('SELECT id, name, email FROM users WHERE email=? AND password_hash=?', (email, password_hash))
        row = c.fetchone()
        conn.close()

        if row:
            session['user_id'] = row[0]
            session['user_name'] = row[1]
            session['user_email'] = row[2]
            flash("Logged in successfully.")
            return redirect(url_for('home'))
        flash("Invalid email or password.")
        return redirect(url_for('login'))

    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    flash("You have been logged out.")
    return redirect(url_for('home'))


# -------- Upload Recipe --------
def _handle_upload_recipe():
    if "user_id" not in session:
        flash("You must be logged in to upload a recipe.")
        return redirect(url_for("login"))

    if request.method == "POST":
        recipe_name  = (request.form.get("recipe_name") or "").strip()
        recipe_type  = (request.form.get("recipe_type") or "").strip()
        ingredients  = request.form.getlist("ingredients[]")
        prep_time    = (request.form.get("prep_time") or "").strip()
        instructions = (request.form.get("instructions") or "").strip()

        if not (recipe_name and recipe_type and ingredients and prep_time and instructions):
            flash("All fields except image are required.")
            return redirect(url_for("upload_recipe"))

        try:
            prep_time_int = int(prep_time)
        except ValueError:
            flash("Prep time must be a number.")
            return redirect(url_for("upload_recipe"))

        image_file = request.files.get("image")
        saved_name = None
        if image_file and image_file.filename and allowed_file(image_file.filename):
            unique = uuid.uuid4().hex
            safe = secure_filename(image_file.filename)
            saved_name = f"{unique}_{safe}"
            image_path = os.path.join(app.config["UPLOAD_FOLDER"], saved_name)
            image_file.save(image_path)

        # Generate AI description
        ai_desc = generate_description(recipe_name, ingredients, recipe_type, prep_time_int)

        con = sqlite3.connect("cookbook.db")
        cur = con.cursor()
        cur.execute("""
            INSERT INTO recipes
              (user_id, recipe_name, recipe_type, ingredients, prep_time, instructions, image_filename, description)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            session["user_id"],
            recipe_name,
            recipe_type,
            json.dumps([s.strip() for s in ingredients if s.strip()]),
            prep_time_int,
            instructions,
            saved_name,
            ai_desc
        ))
        con.commit()
        con.close()

        flash("Recipe uploaded successfully!")
        return redirect(url_for("home"))

    return render_template("recipe-upload.html")


@app.route("/recipe-upload", methods=["GET", "POST"])
def upload_recipe():
    return _handle_upload_recipe()


@app.route("/upload-recipe", methods=["GET", "POST"])  # alias
def upload_recipe_alias():
    return _handle_upload_recipe()


# -------- Discover Page --------
@app.route('/discover')
def discover():
    conn = sqlite3.connect('cookbook.db')
    c = conn.cursor()
    
    c.execute("""
        SELECT recipes.id, recipes.recipe_name, recipes.image_filename, recipes.rating,
               recipes.recipe_type, recipes.prep_time,
               users.id, users.name
        FROM recipes
        JOIN users ON recipes.user_id = users.id
        ORDER BY recipes.id DESC
    """)
    recipes = c.fetchall()
    conn.close()

    return render_template('discover.html', recipes=recipes)



# -------- Admin Clear Recipes --------
@app.route('/admin/clear-recipes')
def clear_recipes():
    if "user_id" not in session:
        flash("You must be logged in.")
        return redirect(url_for('login'))

    conn = sqlite3.connect('cookbook.db')
    c = conn.cursor()
    c.execute("SELECT is_admin FROM users WHERE id=?", (session["user_id"],))
    row = c.fetchone()
    conn.close()

    if not row or row[0] != 1:
        flash("Access denied. Admins only.")
        return redirect(url_for('home'))

    # Clear recipes
    conn = sqlite3.connect('cookbook.db', timeout=5)
    c = conn.cursor()
    c.execute("DELETE FROM recipes")
    conn.commit()
    conn.close()

    # Remove uploaded images
    upload_folder = app.config["UPLOAD_FOLDER"]
    for file_path in glob.glob(os.path.join(upload_folder, "*")):
        try:
            os.remove(file_path)
        except OSError:
            pass

    flash("All recipes and uploaded images have been cleared.")
    return redirect(url_for('home'))


# -------- Recipe Detail --------
@app.route('/recipe/<int:recipe_id>')
def recipe_detail(recipe_id):
    conn = sqlite3.connect('cookbook.db')
    c = conn.cursor()
    c.execute("""
        SELECT recipes.id, recipes.recipe_name, recipes.recipe_type, recipes.ingredients,
            recipes.prep_time, recipes.instructions, recipes.image_filename,
            users.name, recipes.description, recipes.rating
        FROM recipes
        JOIN users ON recipes.user_id = users.id
        WHERE recipes.id = ?
    """, (recipe_id,))
    row = c.fetchone()
    conn.close()

    if not row:
        flash("Recipe not found.")
        return redirect(url_for('discover'))

    recipe = {
        "id": row[0],
        "name": row[1],
        "type": row[2],
        "ingredients": json.loads(row[3]) if row[3] else [],
        "prep_time": row[4],
        "instructions": row[5],
        "image": row[6],
        "author": row[7],
        "description": row[8],
        "rating": row[9]
    }

    return render_template('recipe.html', recipe=recipe)


# -------- Surprise me --------
@app.route('/surprise-me')
def random_recipe():
    conn = sqlite3.connect('cookbook.db')
    c = conn.cursor()
    c.execute("SELECT id FROM recipes ORDER BY RANDOM() LIMIT 1")
    row = c.fetchone()
    conn.close()

    if not row:
        flash("No recipes available.")
        return redirect(url_for('discover'))

    return redirect(url_for('recipe_detail', recipe_id=row[0]))


# -------- Vote on Recipes --------
@app.route('/recipe/<int:recipe_id>/vote/<action>', methods=['POST'])
def vote_recipe(recipe_id, action):
    if "user_id" not in session:
        flash("You must be logged in to vote.")
        return redirect(url_for("login"))

    user_id = session["user_id"]

    # Decide vote value
    if action == "up":
        vote_value = 1   # Yum
    elif action == "down":
        vote_value = -1  # Tomato
    else:
        flash("Invalid vote action.")
        return redirect(url_for("recipe_detail", recipe_id=recipe_id))

    conn = sqlite3.connect("cookbook.db")
    c = conn.cursor()

    # Check if this user already voted
    c.execute("SELECT vote FROM recipe_votes WHERE user_id=? AND recipe_id=?", (user_id, recipe_id))
    existing_vote = c.fetchone()

    if existing_vote:
        if existing_vote[0] == vote_value:
            # Same vote again → undo the vote
            c.execute("DELETE FROM recipe_votes WHERE user_id=? AND recipe_id=?", (user_id, recipe_id))
            c.execute("UPDATE recipes SET rating = rating - ? WHERE id=?", (vote_value, recipe_id))
            flash("Your vote was removed.")
        else:
            # Change the vote (e.g., Yum → Tomato)
            c.execute("UPDATE recipe_votes SET vote=? WHERE user_id=? AND recipe_id=?", (vote_value, user_id, recipe_id))
            c.execute("UPDATE recipes SET rating = rating + (? - ?) WHERE id=?", (vote_value, existing_vote[0], recipe_id))
            flash("Your vote was updated.")
    else:
        # New vote
        c.execute("INSERT INTO recipe_votes (user_id, recipe_id, vote) VALUES (?, ?, ?)", (user_id, recipe_id, vote_value))
        c.execute("UPDATE recipes SET rating = rating + ? WHERE id=?", (vote_value, recipe_id))
        flash("Your vote was recorded.")

    conn.commit()
    conn.close()

    return redirect(url_for("recipe_detail", recipe_id=recipe_id))


# -------- My kitchen --------
@app.route('/my-kitchen')
def my_kitchen():
    if "user_id" not in session:
        flash("You must be logged in to view your kitchen.")
        return redirect(url_for("login"))

    conn = sqlite3.connect("cookbook.db")
    c = conn.cursor()

    # Get user info (name, banner, profile pic)
    c.execute("SELECT name, banner_filename, profile_pic_filename, bio FROM users WHERE id=?", (session["user_id"],))
    user = c.fetchone()


    # Get their recipes
    c.execute("""
        SELECT id, recipe_name, image_filename, rating
        FROM recipes WHERE user_id=?
        ORDER BY created_at DESC
    """, (session["user_id"],))
    recipes = c.fetchall()
    conn.close()

    return render_template("my-kitchen.html", user=user, recipes=recipes)


# -------- Upload Banner --------
@app.route("/upload_banner", methods=["POST"])
def upload_banner():
    if "user_id" not in session:
        flash("Login first.")
        return redirect(url_for("login"))

    file = request.files.get("banner")
    if file and allowed_file(file.filename):
        # generate unique filename
        unique = uuid.uuid4().hex
        safe = secure_filename(file.filename)
        filename = f"{unique}_{safe}"

        filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        file.save(filepath)

        conn = sqlite3.connect("cookbook.db")
        c = conn.cursor()
        c.execute("UPDATE users SET banner_filename = ? WHERE id = ?", (filename, session["user_id"]))
        conn.commit()
        conn.close()

        flash("Banner updated successfully!")

    return redirect(url_for("my_kitchen"))



# -------- Upload Profile Picture --------
@app.route("/upload_profile_pic", methods=["POST"])
def upload_profile_pic():
    if "user_id" not in session:
        flash("Login first.")
        return redirect(url_for("login"))

    file = request.files.get("profile_pic")
    if file and allowed_file(file.filename):
        # check file size (move cursor to end, then back)
        file.seek(0, os.SEEK_END)
        file_size = file.tell()
        file.seek(0)
        if file_size > 2 * 1024 * 1024:  # 2 MB
            flash("Profile picture must be under 2MB.")
            return redirect(url_for("my_kitchen"))

        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        file.save(filepath)

        conn = sqlite3.connect("cookbook.db")
        c = conn.cursor()
        c.execute("UPDATE users SET profile_pic_filename = ? WHERE id = ?", (filename, session["user_id"]))
        conn.commit()
        conn.close()

        flash("Profile picture updated successfully!")
    return redirect(url_for("my_kitchen"))


@app.route('/kitchen/<int:user_id>')
def view_kitchen(user_id):
    conn = sqlite3.connect("cookbook.db")
    c = conn.cursor()

    # fetch user info (name, banner, profile, bio)
    c.execute("SELECT name, banner_filename, profile_pic_filename, bio FROM users WHERE id=?", (user_id,))
    user = c.fetchone()

    if not user:
        conn.close()
        flash("User not found.")
        return redirect(url_for("discover"))

    # fetch user’s recipes
    c.execute("""
        SELECT id, recipe_name, image_filename, rating
        FROM recipes WHERE user_id=?
        ORDER BY created_at DESC
    """, (user_id,))
    recipes = c.fetchall()
    conn.close()

    return render_template("view-kitchen.html", user=user, recipes=recipes)


# ---------------- Run ----------------
if __name__ == '__main__':
    app.run(debug=True)
