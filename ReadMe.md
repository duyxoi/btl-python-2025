# 📚 Library Management System

[![Python](https://img.shields.io/badge/Python-3.9-blue.svg)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Flask-2.0.2-green.svg)](https://flask.palletsprojects.com/)
[![HTML](https://img.shields.io/badge/HTML-5-orange.svg)](https://developer.mozilla.org/en-US/docs/Web/Guide/HTML/HTML5)
[![CSS](https://img.shields.io/badge/CSS-3-blue.svg)](https://developer.mozilla.org/en-US/docs/Web/CSS)

## Overview

The Library Management System is a web-based application designed to efficiently manage the operations of a library. This system provides features for users to browse through available books, search for specific categories, issue books, and provide feedback. Librarians have administrative privileges to manage the entire system, including book management, user management, and feedback management.

## 🌟 Features

### User Features
- **🔍 Browse Books**: Users can view a list of all available books.
- **🔎 Search Books**: Users can search for books by title, author, or category.
- **📖 Issue Books**: Users can issue books, and view their issued book history.
- **📝 Feedback**: Users can provide feedback on books and the library system.

### Librarian Features
- **📚 Book Management**: Add, edit, or remove books from the system.
- **👥 User Management**: View and manage user accounts and their issued books.
- **📩 Feedback Management**: Review and respond to user feedback.

## 🛠️ Technologies Used

The Library Management System is developed using the following technologies:

- <span style="color:orange;">**HTML**</span>: For creating the structure and layout of web pages.
- <span style="color:blue;">**CSS**</span>: For styling the web pages and enhancing the user interface.
- <span style="color:green;">**Flask**</span>: A micro web framework for Python used for server-side development and handling backend operations.
- <span style="color:purple;">**SQLite**</span>: A lightweight relational database management system used for storing and managing library data.

## 🛠️ Installation

To run the Library Management System on your local machine, follow these steps:

1. **Clone the repository**
    ```bash
    git clone https://github.com/yourusername/library-management-system.git
    cd library-management-system
    ```

2. **Install dependencies**
    ```bash
    pip install -r requirements.txt
    ```

3. **Set up the database**
    - The system uses SQLite by default, so no additional setup is required.
    - If using another database, update the configuration in `config.py`.

4. **Run database migrations**
    ```bash
    flask db upgrade
    ```

5. **Start the application**
    ```bash
    flask run
    ```

6. **Access the application**
    - Open your web browser and navigate to `http://localhost:5000`.

## ⚙️ System Features

The key features of the Library Management System include:

- **👤 User Registration and Authentication**: Users can register and login to the system using their credentials.
- **📚 Browse Books**: Users can browse through the collection of books available in the library.
- **🔎 Search and Filter**: Users can search for books based on categories, titles, authors, or keywords.
- **📖 Issue Books**: Users can issue books by providing necessary details such as book ID and user information.
- **📝 Feedback Submission**: Users can provide feedback on books they have read, helping other users make informed decisions.
- **🔧 Librarian Privileges**: Librarians have access to additional functionalities such as adding new books, managing book inventory, managing users, and reviewing feedback.

## 🏛️ System Architecture

The Library Management System follows a client-server architecture where the client interacts with the server through a web interface. The server-side logic is implemented using Flask, which handles requests from clients, processes data, and communicates with the database.

## 💻 User Interfaces

The user interfaces are designed to be intuitive and user-friendly. HTML and CSS are used to create visually appealing web pages with responsive design for compatibility across devices.

- **🏠 Home Page**: Displays featured books, categories, and navigation links.
- **📚 Book Listing Page**: Displays a list of books with search and filter options.
- **🗂️ Category Listings Page**: Displays a list of categories with search and filter options.
- **📋 User Dashboard**: Allows users to manage their profile, view issued books, and submit feedback.
- **🛠️ Librarian Dashboard**: Provides access to administrative functions such as adding/editing books, managing users, and reviewing feedback.

## 🗄️ Database Schema

The Library Management System employs a relational database model using SQLite to manage various entities efficiently. The database schema includes tables for the following entities:

- **👥 Users**: Stores information about registered users including user ID, username, password, email, and role (user or librarian).
- **📚 Books**: Contains details about each book such as book ID, title, author, category ID, availability status, and quantity.
- **🗂️ Categories**: Stores information about different categories of books including category ID and category name.
- **🛒 Cart**: Tracks the books added to the user's cart before issuing them. It includes details like cart ID, user ID, book ID, and quantity.
- **📦 Order**: Records the issued books by users. It includes order ID, user ID, book ID, issue date, and return date.
- **📝 Feedback**: Stores feedback provided by users for books they have read, including feedback ID, user ID, book ID, rating, and comments.

## 📖 Usage

### User Guide

1. **🔐 Registration and Login**
   - Users need to register an account or log in if they already have one.
   
2. **📚 Browsing and Searching Books**
   - Users can browse through the list of available books or use the search feature to find specific books.
   
3. **📖 Issuing Books**
   - Users can issue books by clicking on the "Issue" button next to the desired book.

4. **📝 Providing Feedback**
   - Users can provide feedback on books or the library system through the feedback form.

### Librarian Guide

1. **🔐 Login**
   - Librarians need to log in with their administrator credentials.

2. **📚 Managing Books**
   - Librarians can add new books, edit existing book details, or remove books from the system.

3. **👥 Managing Users**
   - Librarians can view the list of users, manage their issued books, and handle user-related queries.

4. **📩 Managing Feedback**
   - Librarians can view user feedback and respond to their concerns.

### Contributors:

- [Pranav Darak](https://github.com/pranavdarak)
