from collections import namedtuple

BoxStyle = namedtuple('BoxStyle', 'top, left, right, width, height')
LineStyle = namedtuple('LineStyle',
                       'font_family, font_style, font_size, font_weight, text_transform, font_space_width, text_align')
LocationKey = namedtuple('location_key', 'top, left, text')
