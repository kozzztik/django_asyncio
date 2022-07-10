from setuptools import setup, find_packages

__version__ = '0.1'

setup(
    name='django_asyncio',
    version=__version__,
    description='django_asyncio - improve django to support asyncio features',
    long_description="""""",
    author='https://github.com/kozzztik',
    url='https://github.com/kozzztik/django_asyncio',
    packages=find_packages(),
    include_package_data=True,
    license='https://github.com/kozzztik/django_asyncio/blob/master/LICENSE',
    classifiers=[
        'License :: OSI Approved',
        'Intended Audience :: Developers',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
        ],
    )
