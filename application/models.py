import random
import string
import uuid
from sqlalchemy import ForeignKey
from sqlalchemy.orm import relationship
from application.database import db


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(40), nullable=False)
    phone = db.Column(db.String(40), nullable=False, unique=True)
    email = db.Column(db.String(40), nullable=False, unique=True)
    password = db.Column(db.String(40), nullable=False)
    address = db.Column(db.String(80), nullable=False)
    role = db.Column(db.String(40), nullable=True)

    feedbacks = db.relationship('Feedback', backref='user',lazy=True)
    comments = db.relationship('Comment', backref='user', lazy=True)  # ✅ thêm dòng này


    def __init__(self, name, phone, email, password, address, role):
        self.name = name
        self.phone = phone
        self.email = email
        self.password = password
        self.address = address
        self.role = role

    def dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'phone': self.phone,
            'email': self.email,
            'password': self.password,
            'address': self.address,
            'role': self.role
        }

class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.String(255), nullable=True)
    products = db.relationship('Product', backref='products_in_category', lazy=True)

    def __init__(self, name, description):
        self.name = name
        self.description = description

    def __repr__(self):
        return '<Category %r>' % self.name

    def dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
        }

class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(255), nullable=False)
    author = db.Column(db.String(255), nullable=True)
    description = db.Column(db.String(255), nullable=True)
    category = db.Column(db.String(255), nullable=True)
    quantity = db.Column(db.Integer, nullable=False)
    price = db.Column(db.Integer, nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey("category.id"), nullable=False)
    image_url = db.Column(db.String(500), nullable=True)
    detail = db.Column(db.String(3000),nullable=True)

    def __init__(self, name, description, category_id, author, quantity, price, image_url=None,detail = None):
        self.name = name
        self.author = author
        self.description = description
        self.category_id = category_id
        self.quantity = quantity
        self.price = price
        self.image_url = image_url
        self.detail = detail

    def __repr__(self):
        return f"<Product {self.name}>"

    def dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'author': self.author,
            'category': self.category,
            'description': self.description,
            'category_id': self.category_id,
            'price': self.price,
            'quantity': self.quantity,
            'image_url': self.image_url,
            'detail':self.detail
        }

class Cart(db.Model):
    id= db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id= db.Column(db.Integer, db. ForeignKey('user.id'), nullable=False)
    product_id=db.Column(db. Integer, db. ForeignKey('product.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    is_ordered = db.Column(db.Boolean,nullable=False,default=False)
    product = relationship("Product", backref="carts")

    def __init__(self, user_id, product_id, quantity):
        self.user_id = user_id
        self.product_id= product_id
        self.quantity = quantity

    def repr (self):
        return '<Cart%r>' & self.id

    def to_dict(self):
        return{
            'id':self.id,
            'user_id':self.user_id,
            'product_id':self.product_id,
            'quantity':self.quantity,
            'is_ordered':self.is_ordered
        }

import random
import string
from application.database import db

class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    order_id = db.Column(db.String(20), unique=True, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    product_ids = db.Column(db.String(255), nullable=False)
    quantities = db.Column(db.String(255), nullable=False)
    prices = db.Column(db.String(255), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    total_price = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), nullable=True, default='Pending')
    issue_date = db.Column(db.String(20), nullable=True)
    return_date = db.Column(db.String(20), nullable=True)

    def __init__(self, user_id, product_ids, quantities, prices, quantity, total_price, issue_date, return_date, order_id=None):
        self.user_id = user_id
        self.product_ids = product_ids
        self.quantities = quantities
        self.prices = prices
        self.quantity = quantity
        self.total_price = total_price
        self.issue_date = issue_date
        self.return_date = return_date
        if order_id is None:
            self.order_id = self.generate_order_id()
        else:
            self.order_id = order_id

    def generate_order_id(self):
        characters = string.ascii_letters + string.digits
        order_id = ''.join(random.choices(characters, k=10))
        return order_id

    def __repr__(self):
        return '<Order %r>' % self.order_id

    def to_dict(self):
        return {
            'order_id': self.order_id,
            'user_id': self.user_id,
            'product_ids': self.product_ids,
            'quantities': self.quantities,
            'prices': self.prices,
            'quantity': self.quantity,
            'total_price': self.total_price,
            'status': self.status,
            'issue_date': self.issue_date,
            'return_date': self.return_date
        }



class Feedback(db.Model):
    __tablename__ = 'feedbacks'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, ForeignKey('user.id'), nullable=False)
    feedback_text = db.Column(db.String(255), nullable=False)


    def __init__(self, user_id, feedback_text):
        self.user_id = user_id
        self.feedback_text = feedback_text

    def to_dict(self):
        return {
            'phone': self.phone,
            'user_id': self.user_id,
            'feedback_text': self.feedback_text,
        }

from datetime import datetime

class Comment(db.Model):
    __tablename__ = 'comments'
    id = db.Column(db.Integer,primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, ForeignKey('user.id'), nullable=False)
    product_id=db.Column(db. Integer, db. ForeignKey('product.id'), nullable=False)
    comment = db.Column(db.String(1000),nullable=False)
    create_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __init__(self,user_id,product_id,comment):
        self.user_id = user_id
        self.product_id = product_id
        self.comment = comment

    def to_dict(self):
        return{
            'user_id': self.user_id,
            'product_id': self.product_id,
            'comment': self.comment
        }

