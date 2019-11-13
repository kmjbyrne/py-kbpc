from datetime import datetime

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import desc
from sqlalchemy.exc import IntegrityError
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import ColumnProperty
from sqlalchemy.orm import class_mapper
from sqlalchemy.orm import load_only
from sqlalchemy.orm.attributes import InstrumentedAttribute

from flask_kbpc.logging.logger import get_logger

Base = declarative_base()

db = SQLAlchemy()

logger = get_logger()


def check_inputs(cls, field, value):
    if isinstance(field, str):
        key_name = field
    else:
        key_name = field.name

    instrument = getattr(cls, field)
    if instrument.key not in cls.__dict__.keys() or key_name is None:
        raise ValueError('Invalid input field')
    instrument_key = instrument.key
    return {instrument_key: value}


def sessioncommit():
    try:
        db.session.commit()
    except OperationalError as operror:
        logger.info(str(operror))
        db.session.rollback()
        db.session.close()
        db.session.close()
    except IntegrityError as integerror:
        raise integerror
    except Exception as error:
        raise error
    finally:
        logger.info(str('DB execution cycle complete'))


class DeclarativeBase(db.Model):
    __abstract__ = True
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    active = db.Column(db.VARCHAR(2), primary_key=False, default='Y')

    @classmethod
    def normalise(cls, field):
        """
        Checks whether filter or field key is an InstumentedAttribute and returns a usable string instead.
        InstrumentedAttributes are not compatible with queries.

        :param field:
        :return:
        """

        if isinstance(field, InstrumentedAttribute):
            return field.name
        return field

    @classmethod
    def checkfilters(cls, filters):
        resp = {}
        for k, v in filters.items():
            resp[cls.normalise(k)] = v
        return resp

    @classmethod
    def fields(cls, inc=None, exc=None):
        if inc is None:
            inc = []
        if exc is None:
            exc = []

        normalised_fields = []
        for field in list(key for key in cls.keys() if key not in [cls.normalise(e) for e in exc]):
            normalised_fields.append(cls.normalise(field))
        return normalised_fields

    @classmethod
    def makequery(cls):
        try:
            return cls.query
        except Exception as e:
            logger.error(str(e))
            db.session.rollback()
        return cls.query

    @classmethod
    def get_schema(cls, exclude=None):
        if exclude is None:
            exclude = []
        schema = []
        for item in [key for key in list(cls.__table__.columns.keys()) if key not in exclude]:
            schema.append(
                dict(name=item.replace('_', ' '), key=item)
            )
        return schema

    @classmethod
    def keys(cls):
        all_keys = set(cls.__table__.columns.keys())
        relations = set(cls.__mapper__.relationships.keys())
        return all_keys - relations

    @classmethod
    def getkey(cls, field):
        if isinstance(field, InstrumentedAttribute):
            return getattr(cls, field.key)
        return getattr(cls, field)

    def columns(self):
        return [prop.key for prop in class_mapper(self.__class__).iterate_properties if
                isinstance(prop, ColumnProperty)]

    def prepare(self, rel=False, json=True, exc=None):
        """
        This utility function dynamically converts Alchemy model classes into a dict using introspective lookups.
        This saves on manually mapping each model and all the fields. However, exclusions should be noted.
        Such as passwords and protected properties.

        :param json: boolean for whether to return JSON or model instance format data
        :param rel: Whether or not to introspect to FK's
        :param exc: Fields to exclude from query result set
        :return: json data structure of model
        :rtype: dict
        """

        if exc is None:
            exc = ['password']
        else:
            exc.append('password')

        if not json:
            return self

        # Define our model properties here. Columns and Schema relationships
        columns = [col for col in self.__mapper__.columns.keys() if col not in exc]
        mapped_relationships = self.__mapper__.relationships.keys()
        model_dictionary = self.__dict__
        resp = {}

        # First lets map the basic model attributes to key value pairs
        for c in columns:
            try:
                if isinstance(model_dictionary[c], datetime):
                    resp[c] = str(model_dictionary[c])
                else:
                    resp[c] = model_dictionary[c]
            except KeyError:
                pass

        if rel is False or not mapped_relationships:
            return resp

        if rel is True:
            mapped_relationships = mapped_relationships
        elif len(rel):
            mapped_relationships = map(lambda item: item.key, rel)

        # Now map the relationships
        for r in mapped_relationships:
            try:
                if isinstance(getattr(self, r), list):
                    resp[r] = [
                        i.prepare(rel=False, exc=exc) for i in getattr(self, r)
                    ]
                else:
                    resp[r] = getattr(self, r).prepare(rel=False, exc=exc)

            except Exception as error:
                pass
        return resp

    def __eq__(self, comparison):
        if type(self) != type(comparison):
            raise ValueError('Objects are not the same. Cannot compare')
        base = self.columns()
        base_dictionary = self.__dict__
        comp_dictionary = self.__dict__
        flag = True
        for column_name in base:
            if base_dictionary[column_name] != comp_dictionary[column_name]:
                flag = False
                break
        return flag

    @classmethod
    def create(cls, **payload):
        instance = cls()
        instance.update(commit=False, **payload)
        return instance

    def delete(self):
        db.session.delete(self)
        sessioncommit()

    def sdelete(self, _commit=True):
        self.active = 'D'
        sessioncommit()
        return _commit and self.save() or self

    def restore(self, _commit=True):
        self.active = 'Y'
        sessioncommit()
        return _commit and self.save() or self

    def save(self, _commit=True):
        db.session.add(self)
        if _commit:
            sessioncommit()
        return self

    def update(self, _commit=True, **kwargs):
        for attr, value in kwargs.items():
            if attr != 'id' and attr in self.fields():
                setattr(self, attr, value)
        return _commit and self.save() or self

    def commit(self):
        sessioncommit()

    @classmethod
    def purge(cls):
        cls.query.delete()
        sessioncommit()

    def close(self):
        db.session.close()


def create():
    db.create_all()
