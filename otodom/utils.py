import json
import logging
import re
import unicodedata
from urllib.parse import quote

import requests
from scrapper_helpers.utils import caching

from otodom import BASE_URL

REGION_DATA_KEYS = ["city", "voivodeship", "[district_id]", "[street_id]"]

log = logging.getLogger(__file__)


def replace_all(text, dic):
    """
    This method returns the input string, but replaces its characters according to the input dictionary.

    :param text: input string
    :param dic: dictionary containing the changes. key is the character that's supposed to be changed and value is the desired value
    :rtype: string
    :return: String with the according characters replaced
    """
    for i, j in dic.items():
        text = text.replace(i, j)
    return text


def normalize_text(text):
    """
    This method returns the input string, but normalizes is it for use in the url.

    :param text: input string
    :rtype: string
    :return: Normalized string. lowercase, no diacritics, '-' instead of ' '
    """
    return unicodedata.normalize('NFKD', text.lower()).encode('ascii', 'ignore').decode("utf-8").replace(" ", "-")


def get_region_from_autosuggest(region_part):
    """
    This method makes a request to the OtoDom api, asking for the best fitting region for the supplied region_part string.

    :param region_part: input string, it should be a part of an existing region in Poland, either city, street, district or voivodeship
    :rtype: dict
    :return: A dictionary which contents depend on the API response.
    """
    if not region_part:
        return {}
    url = "https://www.otodom.pl/ajax/geo6/autosuggest/?data={0}".format(region_part)
    response = json.loads(get_response_for_url(url).text)[0]
    region_type = response["level"]
    text = response["text"].replace("<strong>", "").replace("</strong>", "").split(", ")

    region_dict = {}

    if region_type == "CITY":
        region_dict["city"] = "{0}{1}{2}".format(normalize_text(text[0]), "_", response["city_id"])
    elif region_type == "DISTRICT":
        region_dict["city"] = "{0}{1}{2}".format(normalize_text(text[1]), "_", response["city_id"])
        region_dict["[district_id]"] = response["district_id"]
    elif region_type == "REGION":
        region_dict["voivodeship"] = normalize_text(text[0])
    elif region_type == "STREET":
        region_dict["city"] = "{0}{1}{2}".format(normalize_text(text[0]), "_", response["city_id"])
        region_dict["[street_id]"] = response["street_id"]

    return region_dict


def get_region_from_filters(filters):
    """
    This method does a similiar thing as :meth:`scrape.utils.get_region_from_autosuggest` but instead of calling the API, it uses the data provided in the filters

    :param filters: dict, see :meth:`scrape.category.get_category` for reference
    :rtype: dict
    :return: A dictionary which contents depend on the filters content.
    """
    region_dict = {
        region_data: filters.get(region_data)
        for region_data in REGION_DATA_KEYS
        if region_data in filters
    }
    return region_dict


def get_url(main_category, detail_category, region, ads_per_page="", page=None, **filters):
    """
    This method builds a ready-to-use url based on the input parameters.

    :param main_category: see :meth:`scrape.category.get_category` for reference
    :param detail_category: see :meth:`scrape.category.get_category` for reference
    :param region: see :meth:`scrape.category.get_category` for reference
    :param ads_per_page: "?nrAdsPerPage=72" can be used to lower the amount of requests
    :param page: page number
    :param filters: see :meth:`scrape.category.get_category` for reference
    :rtype: string
    :return: the url
    """
    page = "page={0}".format(page) if page is not None else ""

    # skip using autosuggest if any region data present in the filters
    if any([region_key in filters for region_key in REGION_DATA_KEYS]):
        region_data = get_region_from_filters(filters)
    else:
        region_data = get_region_from_autosuggest(region)

    city_or_voivodeship = region_data["city"] if "city" in region_data else region_data[
        "voivodeship"] if "voivodeship" in region_data else ""

    if "[district_id]" in region_data:
        filters["[district_id]"] = region_data["[district_id]"]

    if "[street_id]" in region_data:
        filters["[street_id]"] = region_data["[street_id]"]

    # creating base url
    url = "/".join([BASE_URL, main_category, detail_category, city_or_voivodeship])

    # adding building type if exists in filters
    if "building_type" in filters:
        url = url + "/" + filters["building_type"]

    # adding description fragment search if exists in filters
    if "description_fragment" in filters:
        url = url + "/q-" + "-".join(filters["description_fragment"].split())

    # preparing the rest of filters for addition to the url
    filter_list = []
    for key, value in filters.items():
        if isinstance(value, list):
            for item in value:
                filter_list.append("search{}={}".format(quote(key), item))
        else:
            filter_list.append("search{}={}".format(quote(key), value))

    url = url + "&".join([ads_per_page, page, *filter_list])
    log.info(url)
    return url


@caching
def get_response_for_url(url):
    """
    :param url: an url, most likely from the :meth:`scrape.utils.get_url` method
    :return: a requests.response object
    """
    return requests.get(url)


def get_cookie_from(response):
    """
    :param response: a requests.response object
    :rtype: string
    :return: cookie information as string
    """
    cookie = response.headers['Set-Cookie'].split(';')[0]
    return cookie


def get_csrf_token(html_content):
    """
    :param html_content: a requests.response.content object
    :rtype: string
    :return: the CSRF token as string
    """
    found = re.match(r".*csrfToken\s+=(\\|\s)+'(?P<csrf_token>\w+).*", str(html_content))
    csrf_token = found.groupdict().get('csrf_token')
    return csrf_token