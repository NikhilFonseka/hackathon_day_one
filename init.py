from flask import Flask, render_template

def create_app():
    app = Flask(__name__)

    @app.route('/')
    def index():
        # Renders the template located at templates/index.html.jinja
        return render_template('index.html.jinja')

    return app

if __name__ == '__main__':
    app = create_app()
    app.run(debug=True)