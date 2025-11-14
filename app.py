from application import app

if __name__ == '__main__':
    from application.routes import *
    app.run(host='0.0.0.0', port=8000, debug=True)


