# -*- coding: utf-8 -*-
"""
Low-level array interface to the SAC file format.

Functions in this module work directly with NumPy arrays that mirror the SAC
format.  The 'primitives' in this module are the float, int, and string header
arrays, the float data array, and a header dictionary. Convenience functions
are provided to convert between header arrays and more user-friendly
dictionaries.

These read/write routines are very literal; there is almost no value or type
checking, except for byteorder and header/data array length.  File- and array-
based checking routines are provided for additional checks where desired.

"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)
from future.utils import native_str
from future.builtins import *  # NOQA

import os
import sys
import warnings

import numpy as np

from obspy.core.compatibility import from_buffer
from obspy import UTCDateTime

from ..sac import header as HD
from .util import SacIOError, SacInvalidContentError
from .util import is_valid_enum_int


def init_header_arrays(arrays=('float', 'int', 'str'), byteorder='='):
    """
    Initialize arbitrary header arrays.

    Parameters
    ----------
    arrays : tuple of strings {'float', 'int', 'str'}
        Specify which arrays to initialize and the desired order.
        If omitted, returned arrays are ('float', 'int', 'str').
    byteorder : str {'<', '=', '>'}
        Desired byte order of initialized arrays (little, native, big).

    Returns
    -------
    list of numpy.ndarrays
        The desired SAC header arrays.

    """
    out = []
    for itype in arrays:
        if itype == 'float':
            # null float header array
            hf = np.full(70, fill_value=HD.FNULL,
                         dtype=native_str(byteorder + 'f4'))
            out.append(hf)
        elif itype == 'int':
            # null integer header array
            hi = np.full(40, fill_value=HD.INULL,
                         dtype=native_str(byteorder + 'i4'))
            # set logicals to 0, not -1234whatever
            for i, hdr in enumerate(HD.INTHDRS):
                if hdr.startswith('l'):
                    hi[i] = 0
            # TODO: initialize enumerated values to something?
            # calculate distances by default
            hi[HD.INTHDRS.index('lcalda')] = 1
            out.append(hi)
        elif itype == 'str':
            # null string header array
            hs = np.full(24, fill_value=HD.SNULL, dtype=native_str('|S8'))
            out.append(hs)
        else:
            raise ValueError("Unrecognized header array type {}".format(itype))

    return out


def read_sac(source, headonly=False, byteorder=None, checksize=False):
    """
    Read a SAC binary file.

    Parameters
    ----------
    source : str or file-like object
        Full path string for File-like object from a SAC binary file on disk.
        If the latter, open 'rb'.
    headonly : bool
        If headonly is True, only read the header arrays not the data array.
    byteorder : str {'little', 'big'}, optional
        If omitted or None, automatic byte-order checking is done, starting
        with native order. If byteorder is specified and incorrect, a
        SacIOError is raised.
    checksize : bool, default False
        If True, check that the theoretical file size from the header matches
        the size on disk.

    Returns
    -------
    hf, hi, hs : numpy.ndarray
        The float, integer, and string header arrays.
    data : numpy.ndarray or None
        float32 data array. If headonly is True, data will be None.

    Raises
    ------
    ValueError
        Unrecognized byte order.
    IOError
        File not found, incorrect specified byteorder, theoretical file size
        doesn't match header, or header arrays are incorrect length.

    """
    # TODO: rewrite using "with" statement instead of open/close management.
    # check byte order, header array length, file size, npts == data length
    try:
        f = open(source, 'rb')
        is_file_name = True
    except TypeError:
        # source is already a file-like object
        f = source
        is_file_name = False

    is_byteorder_specified = byteorder is not None
    if not is_byteorder_specified:
        byteorder = sys.byteorder

    if byteorder == 'little':
        endian_str = '<'
    elif byteorder == 'big':
        endian_str = '>'
    else:
        raise ValueError("Unrecognized byteorder. Use {'little', 'big'}")

    # --------------------------------------------------------------
    # READ HEADER
    # The sac header has 70 floats, 40 integers, then 192 bytes
    #    in strings. Store them in array (and convert the char to a
    #    list). That's a total of 632 bytes.
    # --------------------------------------------------------------
    hf = from_buffer(f.read(4 * 70), dtype=native_str(endian_str + 'f4'))
    hi = from_buffer(f.read(4 * 40), dtype=native_str(endian_str + 'i4'))
    hs = from_buffer(f.read(24 * 8), dtype=native_str('|S8'))

    if not is_valid_byteorder(hi):
        if is_byteorder_specified:
            # specified but not valid. you dun messed up.
            raise SacIOError("Incorrect byteorder {}".format(byteorder))
        else:
            # not valid, but not specified.
            # swap the dtype interpretation (dtype.byteorder), but keep the
            # bytes, so the arrays in memory reflect the bytes on disk
            hf = hf.newbyteorder('S')
            hi = hi.newbyteorder('S')

    # we now have correct headers, let's use their correct byte order.
    endian_str = hi.dtype.byteorder

    # check header lengths
    if len(hf) != 70 or len(hi) != 40 or len(hs) != 24:
        hf = hi = hs = None
        if not is_file_name:
            f.close()
        raise SacIOError("Cannot read all header values")

    npts = hi[HD.INTHDRS.index('npts')]

    # check file size
    if checksize:
        cur_pos = f.tell()
        f.seek(0, os.SEEK_END)
        length = f.tell()
        f.seek(cur_pos, os.SEEK_SET)
        th_length = (632 + 4 * int(npts))
        if length != th_length:
            msg = "Actual and theoretical file size are inconsistent.\n" \
                  "Actual/Theoretical: {}/{}\n" \
                  "Check that headers are consistent with time series."
            raise SacIOError(msg.format(length, th_length))

    # --------------------------------------------------------------
    # READ DATA
    # --------------------------------------------------------------
    if headonly:
        data = None
    else:
        data = from_buffer(f.read(int(npts) * 4),
                           dtype=native_str(endian_str + 'f4'))

        if len(data) != npts:
            f.close()
            raise SacIOError("Cannot read all data points")

    if is_file_name:
        f.close()

    return hf, hi, hs, data


def read_sac_ascii(source, headonly=False):
    """
    Read a SAC ASCII file.

    Parameters
    ----------
    source : str for File-like object
        Full path or File-like object from a SAC ASCII file on disk.
    headonly : bool
        If headonly is True, only read the header arrays not the data array.

    Returns
    -------
    hf, hi, hs : numpy.ndarray
        The float, integer, and string header arrays.
    data : numpy.ndarray or None
        float32 data array. If headonly is True, data will be None.

    """
    # checks: ASCII-ness, header array length, npts matches data length
    try:
        fh = open(source, 'rb')
        is_file_name = True
    except IOError:
        raise SacIOError("No such file: " + source)
    except TypeError:
        fh = source
        is_file_name = False

    contents = fh.read()

    contents = [_i.rstrip(b"\n\r") for _i in contents.splitlines(True)]
    if len(contents) < 14 + 8 + 8:
        raise SacIOError("%s is not a valid SAC file:" % fh.name)

    # --------------------------------------------------------------
    # parse the header
    #
    # The sac header has 70 floats, 40 integers, then 192 bytes
    #    in strings. Store them in array (and convert the char to a
    #    list). That's a total of 632 bytes.
    # --------------------------------------------------------------
    # read in the float values
    # TODO: use native '=' dtype byteorder instead of forcing little endian?
    hf = np.array([i.split() for i in contents[:14]],
                  dtype=native_str('<f4')).ravel()
    # read in the int values
    hi = np.array([i.split() for i in contents[14: 14 + 8]],
                  dtype=native_str('<i4')).ravel()
    # reading in the string part is a bit more complicated
    # because every string field has to be 8 characters long
    # apart from the second field which is 16 characters long
    # resulting in a total length of 192 characters
    hs, = init_header_arrays(arrays=('str',))
    for i, j in enumerate(range(0, 24, 3)):
        line = contents[14 + 8 + i]
        hs[j:j + 3] = np.fromstring(line, dtype=native_str('|S8'), count=3)
    # --------------------------------------------------------------
    # read in the seismogram points
    # --------------------------------------------------------------
    if headonly:
        data = None
    else:
        data = np.array([i.split() for i in contents[30:]],
                        dtype=native_str('<f4')).ravel()

        npts = hi[HD.INTHDRS.index('npts')]
        if len(data) != npts:
            if is_file_name:
                fh.close()
            raise SacIOError("Cannot read all data points")

    if is_file_name:
        fh.close()

    return hf, hi, hs, data


def write_sac(dest, hf, hi, hs, data=None, byteorder=None):
    """
    Write the header and (optionally) data arrays to a SAC binary file.

    Parameters
    ----------
    dest : str or File-like object
        Full path or File-like object from SAC binary file on disk.
        If data is None, file mode should be 'wb+'.
    hf, hi, hs : numpy.ndarray
        The float, integer, and string header arrays.
    data : numpy.ndarray, optional
        float32 data array.  If omitted or None, it is assumed that the user
        intends to overwrite/modify only the header arrays of an existing file.
        Equivalent to "writehdr".
    byteorder : str {'little', 'big'}, optional
        Desired output byte order.  If omitted, arrays are written as they are.
        If data=None, better make sure the file you're writing to has the same
        byte order as headers you're writing.

    Notes
    -----
    A user can/should not _create_ a header-only binary file.  Use mode 'wb+'
    for data=None (headonly) writing.

    """
    # this function is a hot mess.  clean up the logic.

    # deal with file name versus File-like object, and file mode
    if data is None:
        # file exists, just modify it (don't start from scratch)
        fmode = 'rb+'
    else:
        # start from scratch
        fmode = 'wb+'

    # TODO: use "with" statements (will always closes the file object?)
    try:
        f = open(dest, fmode)
        is_file_name = True
    except IOError:
        raise SacIOError("Cannot open file: " + dest)
    except TypeError:
        f = dest
        is_file_name = False

    if data is None and f.mode != 'rb+':
        # msg = "File mode must be 'wb+' for data=None."
        # raise ValueError(msg)
        msg = "Writing header-only file. Use 'wb+' file mode to update header."
        warnings.warn(msg)

    if byteorder:
        if byteorder == 'little':
            endian_str = '<'
        elif byteorder == 'big':
            endian_str = '>'
        else:
            raise ValueError("Unrecognized byteorder. Use {'little', 'big'}")

        hf = hf.astype(native_str(endian_str + 'f4'))
        hi = hi.astype(native_str(endian_str + 'i4'))
        if data is not None:
            data = data.astype(native_str(endian_str + 'f4'))

    # TODO: make sure all arrays have same byte order

    # actually write everything
    try:
        f.write(hf.data)
        f.write(hi.data)
        f.write(hs.data)
        if data is not None:
            # TODO: this long way of writing it is to make sure that
            # 'f8' data, for example, is correctly cast as 'f4'
            f.write(data.astype(data.dtype.byteorder + 'f4').data)
    except Exception as e:
        if is_file_name:
            f.close()
        msg = "Cannot write SAC-buffer to file: "
        raise SacIOError(msg, f.name, e)

    if is_file_name:
        f.close()


def write_sac_ascii(dest, hf, hi, hs, data=None):
    """
    Write the header and (optionally) data arrays to a SAC ASCII file.

    Parameters
    ----------
    dest : str or File-like object
        Full path or File-like object from SAC ASCII file on disk.
    hf, hi, hs : numpy.ndarray
        The float, integer, and string header arrays.
    data : numpy.ndarray, optional
        float32 data array.  If omitted or None, it is assumed that the user
        intends to overwrite/modify only the header arrays of an existing file.
        Equivalent to "writehdr". If data is None, better make sure the header
        you're writing matches any data already in the file.

    """
    # TODO: fix prodigious use of file open/close for "with" statements.

    if data is None:
        # file exists, just modify it (don't start from scratch)
        fmode = 'r+'
    else:
        # start from scratch
        fmode = 'w+'

    try:
        f = open(dest, fmode)
        is_file_name = True
    except IOError:
        raise SacIOError("Cannot open file: " + dest)
    except TypeError:
        f = dest
        is_file_name = False

    if data is None and f.mode != 'r+':
        msg = "Writing header-only file. Use 'wb+' file mode to update header."
        warnings.warn(msg)

    try:
        np.savetxt(f, np.reshape(hf, (14, 5)), fmt=native_str("%#15.7g"),
                   delimiter='')
        np.savetxt(f, np.reshape(hi, (8, 5)), fmt=native_str("%10d"),
                   delimiter='')
        np.savetxt(f, np.reshape(hs, (8, 3)), fmt=native_str('%-8s'),
                   delimiter='')
    except Exception as e:
        if is_file_name:
            f.close()
        raise(e, "Cannot write header values: " + f.name)

    if data is not None:
        npts = hi[9]
        if npts in (HD.INULL, 0):
            if is_file_name:
                f.close()
            return
        try:
            rows = npts // 5
            np.savetxt(f, np.reshape(data[0:5 * rows], (rows, 5)),
                       fmt=native_str("%#15.7g"), delimiter='')
            np.savetxt(f, data[5 * rows:], delimiter=b'\t')
        except:
            f.close()
            raise SacIOError("Cannot write trace values: " + f.name)

    if is_file_name:
        f.close()


# ---------------------- HEADER ARRAY / DICTIONARY CONVERTERS -----------------
# TODO: this functionality is basically the same as the getters and setters in
#    sac.sactrace. find a way to avoid duplication?
# TODO: put these in sac.util?
def header_arrays_to_dict(hf, hi, hs, nulls=False):
    """
    Returns
    -------
    dict
        The correctly-ordered SAC header values, as a dictionary.
    nulls : bool
        If True, return all values including nulls.

    """
    if nulls:
        items = [(key, val) for (key, val) in zip(HD.FLOATHDRS, hf)] + \
                [(key, val) for (key, val) in zip(HD.INTHDRS, hi)] + \
                [(key, val.decode()) for (key, val) in zip(HD.STRHDRS, hs)]
    else:
        # more readable
        items = [(key, val) for (key, val) in zip(HD.FLOATHDRS, hf)
                 if val != HD.FNULL] + \
                [(key, val) for (key, val) in zip(HD.INTHDRS, hi)
                 if val != HD.INULL] + \
                [(key, val.decode()) for (key, val) in zip(HD.STRHDRS, hs)
                 if val != HD.SNULL]

    header = dict(items)

    # here, we have to append the 2nd kevnm field into the first and remove
    #   it from the dictionary.
    # XXX: kevnm may be null when kevnm2 isn't
    if 'kevnm2' in header:
        if 'kevnm' in header:
            header['kevnm'] = header['kevnm']
            header['kevnm'] += header.pop('kevnm2')
        else:
            header['kevnm'] = header.pop('kevnm2')

    return header


def dict_to_header_arrays(header=None, byteorder='='):
    """
    Returns null hf, hi, hs arrays, optionally filled with values from a
    dictionary.  No header checking.

    byteorder : str {'<', '=', '>'}
        Desired byte order of initialized arrays (little, native, big).

    """
    hf, hi, hs = init_header_arrays(byteorder=byteorder)

    # have to split kevnm into two fields
    # TODO: add .lower() to hdr lookups, for safety
    if header is not None:
        for hdr, value in header.items():
            if hdr in HD.FLOATHDRS:
                hf[HD.FLOATHDRS.index(hdr)] = value
            elif hdr in HD.INTHDRS:
                if not isinstance(value, (np.integer, int)):
                    msg = "Non-integers may be truncated: {} = {}"
                    warnings.warn(msg.format(hdr, value))
                hi[HD.INTHDRS.index(hdr)] = value
            elif hdr in HD.STRHDRS:
                if hdr == 'kevnm':
                    # assumes users will not include a 'kevnm2' key
                    # XXX check for empty or null value?
                    kevnm = '{:<8s}'.format(value[0:8])
                    kevnm2 = '{:<8s}'.format(value[8:16])
                    hs[1] = kevnm.encode('ascii', 'strict')
                    hs[2] = kevnm2.encode('ascii', 'strict')
                else:
                    # TODO: why was encoding done?
                    # hs[HD.STRHDRS.index(hdr)] = value.encode('ascii',
                    #                                          'strict')
                    hs[HD.STRHDRS.index(hdr)] = value
            else:
                raise ValueError("Unrecognized header name: {}.".format(hdr))

    return hf, hi, hs


def validate_sac_content(hf, hi, hs, data, *tests):
    """
    Check validity of loaded SAC file content, such as header/data consistency.

    Parameters
    ----------
    hf, hi, hs: numpy.ndarray
        Float, int, string SAC header arrays, respectively.
    data : numpy.ndarray of float32 or None
        SAC data array.
    tests : str
        One or more of the following validity tests:

        'delta' : Time step "delta" is positive.
        'logicals' : Logical values are 0, 1, or null
        'data_hdrs' : Length, min, mean, max of data array match header values.
        'enums' : Check validity of enumerated values.
        'reftime' : Reference time values in header are all set.
        'reltime' : Relative time values in header are absolutely referenced.
        'all' : Do all tests.

    Raises
    ------
    SacInvalidContentError
        Any of the specified tests fail.
    ValueError
        'data_hdrs' is specified and data is None, empty array
        No tests specified.

    """
    # TODO: move this to util.py and write and use individual test functions,
    # so that all validity checks are in one place?
    ALL = ('delta', 'logicals', 'data_hdrs', 'enums', 'reftime', 'reltime')

    if 'all' in tests:
        tests = ALL

    if not tests:
        raise ValueError("No validation tests specified.")
    elif any([(itest not in ALL) for itest in tests]):
        msg = "Unrecognized validataion test specified"
        raise ValueError(msg)

    if 'delta' in tests:
        dval = hf[HD.FLOATHDRS.index('delta')]
        if not (dval >= 0.0):
            msg = "Header 'delta' must be >= 0."
            raise SacInvalidContentError(msg)

    if 'logicals' in tests:
        for hdr in ('leven', 'lpspol', 'lovrok', 'lcalda'):
            lval = hi[HD.INTHDRS.index(hdr)]
            if lval not in (0, 1, HD.INULL):
                msg = "Header '{}' must be {{{}, {}, {}}}."
                raise SacInvalidContentError(msg.format(hdr, 0, 1, HD.INULL))

    if 'data_hdrs' in tests:
        try:
            isMIN = hf[HD.FLOATHDRS.index('depmin')] == data.min()
            isMAX = hf[HD.FLOATHDRS.index('depmax')] == data.max()
            isMEN = hf[HD.FLOATHDRS.index('depmen')] == data.mean()
            if not all([isMIN, isMAX, isMEN]):
                msg = "Data headers don't match data array."
                raise SacInvalidContentError(msg)
        except (AttributeError, ValueError) as e:
            msg = "Data array is None, empty array, or non-array. " + \
                  "Cannot check data headers."
            raise ValueError(msg)

    if 'enums' in tests:
        for hdr in HD.ACCEPTED_VALS:
            enval = hi[HD.INTHDRS.index(hdr)]
            if not is_valid_enum_int(hdr, enval, allow_null=True):
                msg = "Invalid enumerated value, '{}': {}".format(hdr, enval)
                raise SacInvalidContentError(msg)

    if 'reftime' in tests:
        nzyear = hi[HD.INTHDRS.index('nzyear')]
        nzjday = hi[HD.INTHDRS.index('nzjday')]
        nzhour = hi[HD.INTHDRS.index('nzhour')]
        nzmin = hi[HD.INTHDRS.index('nzmin')]
        nzsec = hi[HD.INTHDRS.index('nzsec')]
        nzmsec = hi[HD.INTHDRS.index('nzmsec')]

        # all header reference time fields are set
        if not all([val != HD.INULL for val in
                    [nzyear, nzjday, nzhour, nzmin, nzsec, nzmsec]]):
            msg = "Null reference time values detected."
            raise SacInvalidContentError(msg)

        # reference time fields are reasonable values
        try:
            UTCDateTime(year=nzyear, julday=nzjday, hour=nzhour, minute=nzmin,
                        second=nzsec, microsecond=nzmsec)
        except ValueError as e:
            raise SacInvalidContentError("Invalid reference time: %s" % str(e))

    if 'reltime' in tests:
        # iztype is set and points to a non-null header value
        iztype_val = hi[HD.INTHDRS.index('iztype')]
        if is_valid_enum_int('iztype', iztype_val, allow_null=False):
            if iztype_val == 9:
                hdr = 'b'
            elif iztype_val == 11:
                hdr = 'o'
            elif val == 12:
                hdr = 'a'
            elif val in range(13, 23):
                hdr = 'it'+str(val-13)

            if hi[HD.FLOATHDRS.index(hdr)] == HD.INULL:
                msg = "Reference header '{}' for iztype '{}' not set."
                raise SacInvalidContentError(msg.format(hdr, iztype_val))

        else:
            msg = "Invalid iztype: {}".format(iztype_val)
            raise SacInvalidContentError(msg)

    return


def is_valid_byteorder(hi):
    nvhdr = hi[HD.INTHDRS.index('nvhdr')]
    return (0 < nvhdr < 20)
