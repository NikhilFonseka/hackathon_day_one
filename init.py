from flask import Flask, render_template

def create_app():
    app = Flask(__name__)

    @app.route('/')
    def index():
        # Renders the template located at templates/signinsignup.html.jinja
        return render_template('signinsignup.html.jinja')

    return app

if __name__ == '__main__':
    app = create_app()
    app.run(debug=True)