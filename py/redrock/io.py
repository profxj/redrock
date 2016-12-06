from __future__ import absolute_import, division, print_function

import sys
from glob import glob
import os.path

import numpy as np
from astropy.io import fits
from astropy.table import Table

from .zbest import find_zbest
from . import Template

#- for python 3 compatibility
if sys.version_info.major > 2:
    basestring = str

#- From https://github.com/desihub/desispec io.util.native_endian
def native_endian(data):
    """Convert numpy array data to native endianness if needed.

    Returns new array if endianness is swapped, otherwise returns input data

    Context:
    By default, FITS data from astropy.io.fits.getdata() are not Intel
    native endianness and scipy 0.14 sparse matrices have a bug with
    non-native endian data.
    """
    if data.dtype.isnative:
        return data
    else:
        return data.byteswap().newbyteorder()

def read_template(filename):
    '''
    Read template from filename
    
    Returns dictionary with keys:
        wave : restframe wavelength array [Angstroms]
        flux : 2D basis set template flux[i, jwave]
        archetype_coeff : 2D[narchetypes, ncoeff] coefficients describing a
            set of archetypes
        type : string descripting template type
        subtype : string describing template subtype
    '''
    if os.path.exists(filename):
        fx = fits.open(filename, memmap=False)
    else:
        xfilename = os.path.join(os.getenv('RR_TEMPLATE_DIR'), filename)
        if os.path.exists(xfilename):
            fx = fits.open(xfilename, memmap=False)
        else:
            raise IOError('unable to find '+filename)

    hdr = fx['BASIS_VECTORS'].header
    wave = hdr['CRVAL1'] + hdr['CDELT1']*np.arange(hdr['NAXIS1'])
    if 'LOGLAM' in hdr and hdr['LOGLAM'] != 0:
        wave = 10**wave

    flux = native_endian(fx['BASIS_VECTORS'].data)

    rrtype = hdr['RRTYPE'].strip().upper()
    if rrtype == 'GALAXY':
        redshifts = 10**np.arange(np.log10(0.1), np.log10(2.0), 4e-4)
    elif rrtype == 'STAR':
        redshifts = np.arange(-0.001, 0.00101, 0.0001)
    elif rrtype == 'QSO':
        redshifts = 10**np.arange(np.log10(0.5), np.log10(4.0), 5e-4)
    else:
        raise ValueError('Unknown redshift range to use for template type {}'.format(rrtype))

    return Template(rrtype, redshifts, wave, flux)

def find_templates(template_dir=None):
    '''
    Return list of redrock-*.fits template files
    
    Search directories in this order, returning results from first one found:
        * template_dir
        * $RR_TEMPLATE_DIR
        * {redrock_code}/templates/
    '''
    if template_dir is None:
        if 'RR_TEMPLATE_DIR' in os.environ:
            template_dir = os.environ['RR_TEMPLATE_DIR']
        else:
            thisdir = os.path.dirname(__file__)
            tempdir = os.path.join(os.path.abspath(thisdir), 'templates')
            if os.path.exists(tempdir):
                template_dir = tempdir
        
    if template_dir is None:
        raise IOError("ERROR: can't find template_dir, $RR_TEMPLATE_DIR, or {rrcode}/templates/")

    return glob(os.path.join(template_dir, 'rrtemplate-*.fits'))

def read_templates(template_list=None, template_dir=None):
    '''
    Return a list of templates from the files in template_list
    
    If template_list is None, use list from find_templates(template_dir)
    If template_list is a filename, return 1-element list with that template
    '''
    if template_list is None:
        template_list = find_templates(template_dir)

    templates = list()
    if isinstance(template_list, basestring) and os.path.isfile(template_list):
        templates.append(read_template(template_list))
    else:
        for tfile in template_list:
            templates.append(read_template(tfile))
    
    if len(templates) == 0:
        raise IOError('No templates found')
    
    return templates
    
def write_zscan(filename, results, clobber=False):
    '''
    Writes redrock.zfind results to filename
    
    The nested dictionary structure of results is mapped into a nested
    group structure of the HDF5 file:
    
    {targetid}/{templatetype}/[z|zchi2|zbest|minchi2|zerr|zwarn]
    
    if clobber=True, replace pre-existing file
    '''
    import h5py
    if clobber and os.path.exists(filename):
        os.remove(filename)

    zbest = find_zbest(results)        
    zbest.write(filename, path='zbest', format='hdf5')

    fx = h5py.File(filename)
    for targetid in results:
        for ttype in results[targetid]:
            for key in results[targetid][ttype]:
                name = 'targets/{}/{}/{}'.format(targetid, ttype, key)
                fx[name] = results[targetid][ttype][key]
    fx.close()
    
def read_zscan(filename):
    '''Return redrock.zfind results stored in hdf5 file as written
    by write_zscan
    
    returns (zbest, results) tuple:
        zbest is a Table with keys TARGETID, Z, ZERR, ZWARN
        results is a nested dictionary results[targetid][templatetype] with keys
            - z: array of redshifts scanned
            - zchi2: array of chi2 fit at each z
            - zbest: best fit redshift (finer resolution fit around zchi2 min)
            - minchi2: chi2 at zbest
            - zerr: uncertainty on zbest
            - zwarn: 0=good, non-0 is a warning flag    
    '''
    import h5py
    zbest = Table.read(filename, format='hdf5', path='zbest')
    fx = h5py.File(filename, mode='r')
    results = dict()
    #- NOTE: this is clumsy iteration
    targets = fx['targets']
    for targetid in targets:
        results[int(targetid)] = dict()
        for ttype in targets[targetid]:
            results[int(targetid)][ttype] = dict()
            for dataname in targets[targetid+'/'+ttype]:
                results[int(targetid)][ttype][dataname] = targets[targetid+'/'+ttype+'/'+dataname].value
                
    return zbest, results
                
            
    