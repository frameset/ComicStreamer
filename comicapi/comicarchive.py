import zipfile
import os
import struct
import sys
import tempfile
import subprocess
import platform
import locale
import shutil
import tarfile

from natsort import natsorted
from unrar import rarfile
from unrar import unrarlib
import unrar.constants
import ctypes
import io
import pylzma
from py7zlib import Archive7z
from unrar import constants

from PIL import Image
try:
    from PIL import WebPImagePlugin
except:
    pass


class OpenableRarFile(rarfile.RarFile):
    def open(self, member):
        #print "opening %s..." % member
        # based on https://github.com/matiasb/python-unrar/pull/4/files
        res = []
        if isinstance(member, rarfile.RarInfo):
            member = member.filename
        archive = unrarlib.RAROpenArchiveDataEx(self.filename, mode=constants.RAR_OM_EXTRACT)
        handle = self._open(archive)
        found, buf = False, []
        def _callback(msg, UserData, P1, P2):
            if msg == constants.UCM_PROCESSDATA:
                data = (ctypes.c_char*P2).from_address(P1).raw
                buf.append(data)
            return 1
        c_callback = unrarlib.UNRARCALLBACK(_callback)
        unrarlib.RARSetCallback(handle, c_callback, 1)
        try:
            rarinfo = self._read_header(handle)
            while rarinfo is not None:
                #print "checking rar archive %s against %s" % (rarinfo.filename, member)
                if rarinfo.filename == member:
                    self._process_current(handle, constants.RAR_TEST)
                    found = True
                else:
                    self._process_current(handle, constants.RAR_SKIP)
                rarinfo = self._read_header(handle)
        except unrarlib.UnrarException:
            raise rarfile.BadRarFile("Bad RAR archive data.")
        finally:
            self._close(handle)
        if not found:
            raise KeyError('There is no item named %r in the archive' % member)
        return ''.join(buf)


if platform.system() == "Windows":
    import _subprocess
import time

import StringIO
try: 
    import Image
    pil_available = True
except ImportError:
    pil_available = False

sys.path.insert(0, os.path.abspath(".") )
#import UnRAR2
#from UnRAR2.rar_exceptions import *

#from settings import ComicTaggerSettings
from comicinfoxml import ComicInfoXml
from comicbookinfo import ComicBookInfo
from comet import CoMet
from genericmetadata import GenericMetadata, PageType
from filenameparser import FileNameParser
from PyPDF2 import PdfFileReader

class MetaDataStyle:
    CBI = 0
    CIX = 1
    COMET = 2
    name = [ 'ComicBookLover', 'ComicRack', 'CoMet' ]

class ZipArchiver:

    def __init__( self, path ):
        self.path = path

    def getArchiveComment( self ):
        zf = zipfile.ZipFile( self.path, 'r' )
        comment = zf.comment
        zf.close()
        return comment

    def setArchiveComment( self, comment ):
        return self.writeZipComment( self.path, comment )

    def readArchiveFile( self, archive_file ):
        data = ""
        zf = zipfile.ZipFile( self.path, 'r' )

        try:
            data = zf.read( archive_file )
        except zipfile.BadZipfile as e:
            print >> sys.stderr, u"bad zipfile [{0}]: {1} :: {2}".format(e, self.path, archive_file)
            zf.close()
            raise IOError
        except Exception as e:
            zf.close()
            print >> sys.stderr, u"bad zipfile [{0}]: {1} :: {2}".format(e, self.path, archive_file)
            raise IOError
        finally:
            zf.close()
        return data

    def removeArchiveFile( self, archive_file ):
        try:
            self.rebuildZipFile(  [ archive_file ] )
        except:
            return False
        else:
            return True

    def writeArchiveFile( self, archive_file, data ):
        #  At the moment, no other option but to rebuild the whole
        #  zip archive w/o the indicated file. Very sucky, but maybe
        # another solution can be found
        try:
            self.rebuildZipFile(  [ archive_file ] )

            #now just add the archive file as a new one
            zf = zipfile.ZipFile(self.path, mode='a', compression=zipfile.ZIP_DEFLATED )
            zf.writestr( archive_file, data )
            zf.close()
            return True
        except:
            return False

    def getArchiveFilenameList( self ):
        try:
            zf = zipfile.ZipFile( self.path, 'r' )
            namelist = zf.namelist()
            zf.close()
            return namelist
        except Exception as e:
            print >> sys.stderr, u"Unable to get zipfile list [{0}]: {1}".format(e, self.path)
            return []

    # zip helper func
    def rebuildZipFile( self, exclude_list ):

        # this recompresses the zip archive, without the files in the exclude_list
        #print ">> sys.stderr, Rebuilding zip {0} without {1}".format( self.path, exclude_list )

        # generate temp file
        tmp_fd, tmp_name = tempfile.mkstemp( dir=os.path.dirname(self.path) )
        os.close( tmp_fd )

        zin = zipfile.ZipFile (self.path, 'r')
        zout = zipfile.ZipFile (tmp_name, 'w')
        for item in zin.infolist():
            buffer = zin.read(item.filename)
            if ( item.filename not in exclude_list ):
                zout.writestr(item, buffer)

        #preserve the old comment
        zout.comment = zin.comment

        zout.close()
        zin.close()

        # replace with the new file
        os.remove( self.path )
        os.rename( tmp_name, self.path )


    def writeZipComment( self, filename, comment ):
        """
        This is a custom function for writing a comment to a zip file,
        since the built-in one doesn't seem to work on Windows and Mac OS/X

        Fortunately, the zip comment is at the end of the file, and it's
        easy to manipulate.  See this website for more info:
        see: http://en.wikipedia.org/wiki/Zip_(file_format)#Structure
        """

        #get file size
        statinfo = os.stat(filename)
        file_length = statinfo.st_size

        try:
            fo = open(filename, "r+b")

            #the starting position, relative to EOF
            pos = -4

            found = False
            value = bytearray()

            # walk backwards to find the "End of Central Directory" record
            while ( not found ) and ( -pos != file_length ):
                # seek, relative to EOF
                fo.seek( pos,  2)

                value = fo.read( 4 )

                #look for the end of central directory signature
                if bytearray(value) == bytearray([ 0x50, 0x4b, 0x05, 0x06 ]):
                    found = True
                else:
                    # not found, step back another byte
                    pos = pos - 1
                #print pos,"{1} int: {0:x}".format(bytearray(value)[0], value)

            if found:

                # now skip forward 20 bytes to the comment length word
                pos += 20
                fo.seek( pos,  2)

                # Pack the length of the comment string
                format = "H"                   # one 2-byte integer
                comment_length = struct.pack(format, len(comment)) # pack integer in a binary string

                # write out the length
                fo.write( comment_length )
                fo.seek( pos+2,  2)

                # write out the comment itself
                fo.write( comment )
                fo.truncate()
                fo.close()
            else:
                raise Exception('Failed to write comment to zip file!')
        except:
            return False
        else:
            return True

    def copyFromArchive( self, otherArchive ):
        # Replace the current zip with one copied from another archive
        try:
            zout = zipfile.ZipFile (self.path, 'w')
            for fname in otherArchive.getArchiveFilenameList():
                data = otherArchive.readArchiveFile( fname )
                if data is not None:
                    zout.writestr( fname, data )
            zout.close()

            #preserve the old comment
            comment = otherArchive.getArchiveComment()
            if comment is not None:
                if not self.writeZipComment( self.path, comment ):
                    return False
        except  Exception as e:
            print >> sys.stderr, u"Error while copying to {0}: {1}".format(self.path, e)
            return False
        else:
            return True

class SevenZipArchiver:

    def __init__( self, path ):
        self.path = path

    def getArchiveComment( self ):
	#fp = open( self.path, 'r' )
        #szf = Archive7z( fp )
        #comment = szf.comment
	#fp.close()
        #return comment
	return ""

    def setArchiveComment( self, comment ):
	return False

    def readArchiveFile( self, archive_file ):
        data = ""
	fp = open( self.path, 'r' )

        try:
	    szf = Archive7z( fp )
	    data = szf.getmember( archive_file ).read()
        except Exception as e:
            fp.close()
            print >> sys.stderr, u"bad 7zip file [{0}]: {1} :: {2}".format(e, self.path, archive_file)
            raise IOError
        finally:
            fp.close()
        return data

    def removeArchiveFile( self, archive_file ):
	return False
        
    def writeArchiveFile( self, archive_file, data ):
	return False

    def getArchiveFilenameList( self ):
        try:
            fp = open( self.path, 'r' )
	    szf = Archive7z( fp )
            namelist = list(szf.getnames())
            fp.close()
            return namelist
        except Exception as e:
            print >> sys.stderr, u"Unable to get 7zipfile list [{0}]: {1}".format(e, self.path)
            return []

class TarArchiver:

    def __init__( self, path ):
        self.path = path

    def getArchiveComment( self ):
        return ""

    def setArchiveComment( self, comment ):
        return False
    
    def readArchiveFile( self, archive_file ):
        data = ""
        zf = tarfile.TarFile( self.path, 'r' )
        try:
            data = zf.extractfile(archive_file).read()
        except Exception as e:
            zf.close()
            print >> sys.stderr, u"bad tarfile [{0}]: {1} :: {2}".format(e, self.path, archive_file)
            raise IOError
        finally:
            zf.close()
        return data

    def removeArchiveFile( self, archive_file ):
        return False
    
    def writeArchiveFile( self, archive_file, data ):
        return False

    def getArchiveFilenameList( self ):
        try:
            zf = tarfile.TarFile( self.path, 'r' )
            namelist = zf.getnames()
            zf.close()
            return namelist
        except Exception as e:
            print >> sys.stderr, u"Unable to get tarfile list [{0}]: {1}".format(e, self.path)
            return []

#------------------------------------------
# RAR implementation

class RarArchiver:

    devnull = None
    def __init__( self, path, rar_exe_path ):
        self.path = path
        self.rar_exe_path = rar_exe_path

        if RarArchiver.devnull is None:
            RarArchiver.devnull = open(os.devnull, "w")

        # windows only, keeps the cmd.exe from popping up
        if platform.system() == "Windows":
            self.startupinfo = subprocess.STARTUPINFO()
            self.startupinfo.dwFlags |= _subprocess.STARTF_USESHOWWINDOW
        else:
            self.startupinfo = None

    def __del__(self):
        #RarArchiver.devnull.close()
        pass

    def getArchiveComment( self ):

        rarc = self.getRARObj()
        return rarc.comment

    def setArchiveComment( self, comment ):

        if self.rar_exe_path is not None:
            try:
                # write comment to temp file
                tmp_fd, tmp_name = tempfile.mkstemp()
                f = os.fdopen(tmp_fd, 'w+b')
                f.write( comment )
                f.close()

                working_dir = os.path.dirname( os.path.abspath( self.path ) )

                # use external program to write comment to Rar archive
                subprocess.call([self.rar_exe_path, 'c', '-w' + working_dir , '-c-', '-z' + tmp_name, self.path],
                    startupinfo=self.startupinfo,
                    stdout=RarArchiver.devnull)

                if platform.system() == "Darwin":
                    time.sleep(1)

                os.remove( tmp_name)
            except:
                return False
            else:
                return True
        else:
            return False

    def readArchiveFile( self, archive_file ):

        # Make sure to escape brackets, since some funky stuff is going on
        # underneath with "fnmatch"
        #archive_file = archive_file.replace("[", '[[]')
        entries = []

        rarc = self.getRARObj()

        tries = 0
        while tries < 7:
            try:
                tries = tries+1
                #tmp_folder = tempfile.mkdtemp()
                #tmp_file = os.path.join(tmp_folder, archive_file)
                #rarc.extract(archive_file, tmp_folder)
                data = rarc.open(archive_file)
                #data = open(tmp_file).read()
                entries = [(rarc.getinfo(archive_file), data)]


                #shutil.rmtree(tmp_folder, ignore_errors=True)

                #entries = rarc.read_files( archive_file )

                if entries[0][0].file_size != len(entries[0][1]):
                    print >> sys.stderr, u"readArchiveFile(): [file is not expected size: {0} vs {1}]  {2}:{3} [attempt # {4}]".format(
                                entries[0][0].file_size,len(entries[0][1]), self.path, archive_file, tries)
                    continue

            except (OSError, IOError) as e:
                print >> sys.stderr, u"readArchiveFile(): [{0}]  {1}:{2} attempt#{3}".format(str(e), self.path, archive_file, tries)
                time.sleep(1)
            except Exception as e:
                print >> sys.stderr, u"Unexpected exception in readArchiveFile(): [{0}] for {1}:{2} attempt#{3}".format(str(e), self.path, archive_file, tries)
                break

            else:
                #Success"
                #entries is a list of of tuples:  ( rarinfo, filedata)
                if tries > 1:
                    print >> sys.stderr, u"Attempted read_files() {0} times".format(tries)
                if (len(entries) == 1):
                    return entries[0][1]
                else:
                    raise IOError

        raise IOError



    def writeArchiveFile( self, archive_file, data ):

        if self.rar_exe_path is not None:
            try:
                tmp_folder = tempfile.mkdtemp()

                tmp_file = os.path.join( tmp_folder, archive_file )

                working_dir = os.path.dirname( os.path.abspath( self.path ) )

                # TODO: will this break if 'archive_file' is in a subfolder. i.e. "foo/bar.txt"
                # will need to create the subfolder above, I guess...
                f = open(tmp_file, 'w')
                f.write( data )
                f.close()

                # use external program to write file to Rar archive
                subprocess.call([self.rar_exe_path, 'a', '-w' + working_dir ,'-c-', '-ep', self.path, tmp_file],
                    startupinfo=self.startupinfo,
                    stdout=RarArchiver.devnull)

                if platform.system() == "Darwin":
                    time.sleep(1)
                os.remove( tmp_file)
                os.rmdir( tmp_folder)
            except:
                return False
            else:
                return True
        else:
            return False

    def removeArchiveFile( self, archive_file ):
        if self.rar_exe_path is not None:
            try:
                # use external program to remove file from Rar archive
                subprocess.call([self.rar_exe_path, 'd','-c-', self.path, archive_file],
                    startupinfo=self.startupinfo,
                    stdout=RarArchiver.devnull)

                if platform.system() == "Darwin":
                    time.sleep(1)
            except:
                return False
            else:
                return True
        else:
            return False

    def getArchiveFilenameList( self ):

        rarc = self.getRARObj()
        #namelist = [ item.filename for item in rarc.infolist() ]
        #return namelist

        tries = 0
        while tries < 7:
            try:
                tries = tries+1
                #namelist = [ item.filename for item in rarc.infolist() ]
                namelist = []
                for item in rarc.infolist():
                    if item.file_size != 0:
                        namelist.append( item.filename )

            except (OSError, IOError) as e:
                print >> sys.stderr, u"getArchiveFilenameList(): [{0}] {1} attempt#{2}".format(str(e), self.path, tries)
                time.sleep(1)

            else:
                #Success"
                return namelist

        raise e


    def getRARObj( self ):
        tries = 0
        while tries < 7:
            try:
                tries = tries+1
                #rarc = UnRAR2.RarFile( self.path )
                rarc = OpenableRarFile(self.path)

            except (OSError, IOError) as e:
                print >> sys.stderr, u"getRARObj(): [{0}] {1} attempt#{2}".format(str(e), self.path, tries)
                time.sleep(1)

            else:
                #Success"
                return rarc

        raise e

#------------------------------------------
# Folder implementation
class FolderArchiver:

    def __init__( self, path ):
        self.path = path
        self.comment_file_name = "ComicTaggerFolderComment.txt"

    def getArchiveComment( self ):
        return self.readArchiveFile( self.comment_file_name )

    def setArchiveComment( self, comment ):
        return self.writeArchiveFile( self.comment_file_name, comment )

    def readArchiveFile( self, archive_file ):

        data = ""
        fname = os.path.join( self.path, archive_file )
        try:
            with open( fname, 'rb' ) as f:
                data = f.read()
                f.close()
        except IOError as e:
            pass

        return data

    def writeArchiveFile( self, archive_file, data ):

        fname = os.path.join( self.path, archive_file )
        try:
            with open(fname, 'w+') as f:
                f.write( data )
                f.close()
        except:
            return False
        else:
            return True

    def removeArchiveFile( self, archive_file ):

        fname = os.path.join( self.path, archive_file )
        try:
            os.remove( fname )
        except:
            return False
        else:
            return True

    def getArchiveFilenameList( self ):
        return self.listFiles( self.path )

    def listFiles( self, folder ):

        itemlist = list()

        for item in os.listdir( folder ):
            itemlist.append( item )
            if os.path.isdir( item ):
                itemlist.extend( self.listFiles( os.path.join( folder, item ) ))

        return itemlist

#------------------------------------------
# Unknown implementation
class UnknownArchiver:

    def __init__( self, path ):
        self.path = path

    def getArchiveComment( self ):
        return ""
    def setArchiveComment( self, comment ):
        return False
    def readArchiveFile( self ):
        return ""
    def writeArchiveFile( self, archive_file, data ):
        return False
    def removeArchiveFile( self, archive_file ):
        return False
    def getArchiveFilenameList( self ):
        return []

class PdfArchiver:
    def __init__( self, path ):
        self.path = path

    def getArchiveComment( self ):
        return ""
    def setArchiveComment( self, comment ):
        return False
    def readArchiveFile( self, page_num ):
        resolution = 300
        #return subprocess.check_output(['pdftopng', '-r', str(resolution), '-f', str(int(os.path.basename(page_num)[:-4])), '-l', str(int(os.path.basename(page_num)[:-4])), self.path,  '-'])
        return subprocess.check_output(['mudraw', '-r', str(resolution), '-o','-', self.path, str(int(os.path.basename(page_num)[:-4]))])

    def writeArchiveFile( self, archive_file, data ):
        return False
    def removeArchiveFile( self, archive_file ):
        return False
    def getArchiveFilenameList( self ):
        out = []
        try:
            pdf = PdfFileReader(open(self.path, 'rb'))
            if pdf.isEncrypted:
                try:
                    pdf.decrypt('')
                    for page in range(1, pdf.getNumPages() + 1):
                        out.append(str(page) + ".jpg")
                except Exception as e:
                    print >> sys.stderr, u"PDF Decrypted Failed [{0}]: {1}".format(str(e),self.path)
            else:
                for page in range(1, pdf.getNumPages() + 1):
                    #out.append("/%04d.jpg" % (page))

                    out.append(str(page) + ".jpg")
                    
        except Exception as e:
            print >> sys.stderr, u"PDF Unreadable [{0}]: {1}".format(str(e),self.path)
        return out

class EpubArchiver:
    def __init__( self, path ):
        self.path = path
    
    def getArchiveComment( self ):
        return ""
    def setArchiveComment( self, comment ):
        return False
    def readArchiveFile( self, page_num ):
        corrected_path = self.path
        if os.path.basename(self.path)[-4:] == 'epub':
            corrected_path = self.path + u".tmp.pdf"
        resolution = 300;
        return subprocess.check_output(['mudraw', '-r', str(resolution), '-o','-', corrected_path, str(int(os.path.basename(page_num)[:-4]))])
    def writeArchiveFile( self, archive_file, data ):
        return False
    def removeArchiveFile( self, archive_file ):
        return False
    def getArchiveFilenameList( self ):
        out = []
        try:
            corrected_path = self.path
            if os.path.basename(self.path)[-4:] == 'epub':
                if not os.path.isfile(self.path+ u".tmp.pdf"):
                    subprocess.check_output(['/Applications/calibre.app/Contents/MacOS/ebook-convert', self.path, self.path + u".tmp.pdf"])
                #rename file after process is done... tmp cache
                corrected_path = self.path + u".tmp.pdf"
            pdf = PdfFileReader(open(corrected_path, 'rb'))
            if pdf.isEncrypted:
                try:
                    pdf.decrypt('')
                    for page in range(1, pdf.getNumPages() + 1):
                        out.append("/%04d.jpg" % (page))
                except Exception as e:
                    print >> sys.stderr, u"PDF Decrypted Failed [{0}]: {1}".format(str(e),self.path)
            else:
                for page in range(1, pdf.getNumPages() + 1):
                    #out.append("/%04d.jpg" % (page))
                    out.append(str(page))
        except Exception as e:
            print >> sys.stderr, u"PDF Unreadable [{0}]: {1}".format(str(e),corrected_path)
        return out

#------------------------------------------------------------------


class ComicArchive:

    logo_data = None

    class ArchiveType:
        Zip, SevenZip, Rar, Folder, Pdf, Epub, Tar, Unknown = range(8)
    
    def __init__( self, path, rar_exe_path=None, default_image_path=None ):
        self.path = path

#CACHE PDF,EPUB HERE
        self.rar_exe_path = rar_exe_path
        self.ci_xml_filename = 'ComicInfo.xml'
        self.comet_default_filename = 'CoMet.xml'
        self.resetCache()
        self.default_image_path = default_image_path

        # Use file extension to decide which archive test we do first
        ext = os.path.splitext(path)[1].lower()

        self.archive_type =  self.ArchiveType.Unknown
        self.archiver = UnknownArchiver( self.path )

        # test all known types even if they have the wrong extension
        if ext == ".cbr" or ext == ".rar":
            if self.rarTest():
                self.archive_type =  self.ArchiveType.Rar
                self.archiver = RarArchiver( self.path, rar_exe_path=self.rar_exe_path )

            elif self.zipTest():
                self.archive_type =  self.ArchiveType.Zip
                self.archiver = ZipArchiver( self.path )

            elif self.sevenZipTest():
                self.archive_type = self.ArchiveType.SevenZip
                self.archiver = SevenZipArchiver( self.path )

            elif self.tarTest():
                self.archive_type = self.ArchiveType.Tar
                self.archiver = TarArchiver( self.path )
    
        elif ext == ".cbz" or ext == ".zip":
            if self.zipTest():
                self.archive_type = self.ArchiveType.Zip
                self.archiver = ZipArchiver( self.path )
            
            elif self.sevenZipTest():
                self.archive_type = self.ArchiveType.SevenZip
                self.archiver = SevenZipArchiver( self.path )

            elif self.rarTest():
                self.archive_type =  self.ArchiveType.Rar
                self.archiver = RarArchiver( self.path, rar_exe_path=self.rar_exe_path )

            elif self.tarTest():
                self.archive_type = self.ArchiveType.Tar
                self.archiver = TarArchiver( self.path )
                
        elif ext == ".cb7" or ext == ".7z":
            if self.sevenZipTest():
                self.archive_type = self.ArchiveType.SevenZip
                self.archiver = SevenZipArchiver( self.path )

            elif self.zipTest():
                self.archive_type = self.ArchiveType.Zip
                self.archiver = ZipArchiver( self.path )

            elif self.rarTest():
                self.archive_type =  self.ArchiveType.Rar
                self.archiver = RarArchiver( self.path, rar_exe_path=self.rar_exe_path )

            elif self.tarTest():
                self.archive_type = self.ArchiveType.Tar
                self.archiver = TarArchiver( self.path )
        elif ext == ".cbt" or ext == ".tar":
            
            if self.tarTest():
                self.archive_type = self.ArchiveType.Tar
                self.archiver = TarArchiver( self.path )

            elif self.sevenZipTest():
                self.archive_type = self.ArchiveType.SevenZip
                self.archiver = SevenZipArchiver( self.path )

            elif self.zipTest():
                self.archive_type =  self.ArchiveType.Zip
                self.archiver = ZipArchiver( self.path )

            elif self.rarTest():
                self.archive_type =  self.ArchiveType.Rar
                self.archiver = RarArchiver( self.path, rar_exe_path=self.rar_exe_path )

        else:
            if os.path.basename(self.path)[-3:] == 'pdf':
                if os.path.basename(self.path)[-8:] != '.tmp.pdf':
                    self.archive_type = self.ArchiveType.Pdf
                    self.archiver = PdfArchiver(self.path)

            #elif os.path.basename(self.path)[-4:] == 'epub':
            #self.archive_type = self.ArchiveType.Epub
            #self.archiver = EpubArchiver(self.path)

            elif self.zipTest():
                self.archive_type =  self.ArchiveType.Zip
                self.archiver = ZipArchiver( self.path )

            elif self.rarTest():
                self.archive_type =  self.ArchiveType.Rar
                self.archiver = RarArchiver( self.path, rar_exe_path=self.rar_exe_path )

            elif self.sevenZipTest():
                self.archive_type = self.ArchiveType.SevenZip
                self.archiver = SevenZipArchiver( self.path )

            elif self.tarTest():
                self.archive_type = self.ArchiveType.Tar
                self.archiver = TarArchiver( self.path )

        if ComicArchive.logo_data is None:
            #fname = ComicTaggerSettings.getGraphic('nocover.png')
            fname = self.default_image_path
            with open(fname, 'rb') as fd:
                ComicArchive.logo_data = fd.read()

    # Clears the cached data
    def resetCache( self ):
        self.has_cix = None
        self.has_cbi = None
        self.has_comet = None
        self.comet_filename = None
        self.page_count  = None
        self.page_list  = None
        self.cix_md  = None
        self.cbi_md  = None
        self.comet_md  = None

    def loadCache( self, style_list ):
        for style in style_list:
            self.readMetadata(style)

    def rename( self, path ):
        self.path = path
        self.archiver.path = path


    def zipTest( self ):
        return zipfile.is_zipfile( self.path )


    def sevenZipTest( self ):
	try: 
	    Archive7z(open(self.path)).getnames()
	except:
	    return False
	else: 
	    return True


    def tarTest( self ):
	try: 
	    return tarfile.is_tarfile( self.path )
	except:
	    return False
	else: 
	    return True


    def rarTest( self ):
        try:
            rarc = rarfile.RarFile( self.path )
        except: # InvalidRARArchive:
            return False
        else:
            return True


    def isZip( self ):
        return self.archive_type ==  self.ArchiveType.Zip
    def isSevenZip( self ):
        return self.archive_type ==  self.ArchiveType.SevenZip
    def isRar( self ):
        return self.archive_type ==  self.ArchiveType.Rar
    def isPdf(self):
        return self.archive_type ==  self.ArchiveType.Pdf
    def isEpub(self):
        return self.archive_type ==  self.ArchiveType.Epub
    def isTar(self):
        return self.archive_type ==  self.ArchiveType.Tar
    def isFolder( self ):
        return self.archive_type ==  self.ArchiveType.Folder

    def isWritable( self, check_rar_status=True ):
        if self.archive_type == self.ArchiveType.Unknown :
            return False

        elif check_rar_status and self.isRar() and self.rar_exe_path is None:
            return False

        elif self.isSevenZip():
            return False

        elif self.isPdf():
            return False

        elif self.isEpub():
            return False

        elif self.isTar():
            return False

        elif not os.access(self.path, os.W_OK):
            return False

        elif ((self.archive_type != self.ArchiveType.Folder) and
                (not os.access( os.path.dirname( os.path.abspath(self.path)), os.W_OK ))):
            return False

        return True

    def isWritableForStyle( self, data_style ):

        if self.isRar() and data_style == MetaDataStyle.CBI:
            return False

        return self.isWritable()

    def seemsToBeAComicArchive( self ):

        # Do we even care about extensions??
        ext = os.path.splitext(self.path)[1].lower()

        if (
              ( self.isZip() or self.isTar() or  self.isRar() or self.isPdf() or self.isEpub() or self.isSevenZip() ) #or self.isFolder() )
              and
              ( self.getNumberOfPages() > 0)

            ):
            return True
        else:
            return False

    def readMetadata( self, style ):

        if style == MetaDataStyle.CIX:
            return self.readCIX()
        elif style == MetaDataStyle.CBI:
            return self.readCBI()
        elif style == MetaDataStyle.COMET:
            return self.readCoMet()
        else:
            return GenericMetadata()

    def writeMetadata( self, metadata, style ):

        retcode = None
        if style == MetaDataStyle.CIX:
            retcode = self.writeCIX( metadata )
        elif style == MetaDataStyle.CBI:
            retcode = self.writeCBI( metadata )
        elif style == MetaDataStyle.COMET:
            retcode = self.writeCoMet( metadata )
        return retcode


    def hasMetadata( self, style ):

        if style == MetaDataStyle.CIX:
            return self.hasCIX()
        elif style == MetaDataStyle.CBI:
            return self.hasCBI()
        elif style == MetaDataStyle.COMET:
            return self.hasCoMet()
        else:
            return False

    def removeMetadata( self, style ):
        retcode = True
        if style == MetaDataStyle.CIX:
            retcode = self.removeCIX()
        elif style == MetaDataStyle.CBI:
            retcode = self.removeCBI()
        elif style == MetaDataStyle.COMET:
            retcode = self.removeCoMet()
        return retcode

    def getPage( self, index ):

        image_data = None

        filename = self.getPageName( index )
       
        if filename is not None:
            try:

                image_data = self.archiver.readArchiveFile( filename )
            except IOError:
                print >> sys.stderr, u"Error reading in page.  Substituting logo page."
                image_data = ComicArchive.logo_data
        try:
                Image.open(StringIO.StringIO(image_data))
        except IOError:
            print >> sys.stderr, u"Error reading in page.  Substituting logo page."
            image_data = ComicArchive.logo_data
        return image_data

    def getPageName( self, index ):

        if index is None:
            return None

        page_list = self.getPageNameList()

        num_pages = len( page_list )
        if num_pages == 0 or index >= num_pages:
            return None

        return  page_list[index]

    def getScannerPageIndex( self ):

        scanner_page_index = None

        #make a guess at the scanner page
        name_list = self.getPageNameList()
        count = self.getNumberOfPages()

        #too few pages to really know
        if count < 5:
            return None

        # count the length of every filename, and count occurences
        length_buckets = dict()
        for name in name_list:
            fname =  os.path.split(name)[1]
            length = len(fname)
            if length_buckets.has_key( length ):
                length_buckets[ length ] += 1
            else:
                length_buckets[ length ] = 1

        # sort by most common
        sorted_buckets = sorted(length_buckets.iteritems(), key=lambda (k,v): (v,k), reverse=True)

        # statistical mode occurence is first
        mode_length = sorted_buckets[0][0]

        # we are only going to consider the final image file:
        final_name = os.path.split(name_list[count-1])[1]

        common_length_list = list()
        for name in name_list:
            if len(os.path.split(name)[1]) == mode_length:
                common_length_list.append( os.path.split(name)[1] )

        prefix = os.path.commonprefix(common_length_list)

        if mode_length <= 7 and prefix == "":
            #probably all numbers
            if len(final_name) > mode_length:
                scanner_page_index = count-1

        # see if the last page doesn't start with the same prefix as most others
        elif not final_name.startswith(prefix):
            scanner_page_index = count-1

        return scanner_page_index


    def getPageNameList( self , sort_list=True):

        if self.page_list is None:
            # get the list file names in the archive, and sort
            files = self.archiver.getArchiveFilenameList()

            # seems like some archive creators are on  Windows, and don't know about case-sensitivity!
            if sort_list:
                def keyfunc(k):
                    #hack to account for some weird scanner ID pages
                    #basename=os.path.split(k)[1]
                    #if basename < '0':
                    #	k = os.path.join(os.path.split(k)[0], "z" + basename)
                    return k.lower()

                files = natsorted(files, key=keyfunc,signed=False)

            # make a sub-list of image files
            self.page_list = []
            for name in files:
                if ( name[-4:].lower() in [".bmp", ".jpg", "jpeg", ".png", ".gif", "webp" ] and os.path.basename(name)[0] != "." ):
                    self.page_list.append(name)

        return self.page_list

    def getNumberOfPages( self ):

        if self.page_count is None:
            self.page_count = len( self.getPageNameList( ) )
        return self.page_count

    def readCBI( self ):
        if self.cbi_md is None:
            raw_cbi = self.readRawCBI()
            if raw_cbi is None:
                self.cbi_md = GenericMetadata()
            else:
                self.cbi_md = ComicBookInfo().metadataFromString( raw_cbi )

            self.cbi_md.setDefaultPageList( self.getNumberOfPages() )

        return self.cbi_md

    def readRawCBI( self ):
        if ( not self.hasCBI() ):
            return None

        return self.archiver.getArchiveComment()

    def hasCBI(self):
        if self.has_cbi is None:

            #if ( not ( self.isZip() or self.isRar()) or not self.seemsToBeAComicArchive() ):
            if not self.seemsToBeAComicArchive():
                self.has_cbi = False
            else:
                comment = self.archiver.getArchiveComment()
                self.has_cbi = ComicBookInfo().validateString( comment )

        return self.has_cbi

    def writeCBI( self, metadata ):
        if metadata is not None:
            self.applyArchiveInfoToMetadata( metadata )
            cbi_string = ComicBookInfo().stringFromMetadata( metadata )
            write_success =  self.archiver.setArchiveComment( cbi_string )
            if write_success:
                self.has_cbi = True
                self.cbi_md = metadata
            self.resetCache()
            return write_success
        else:
            return False

    def removeCBI( self ):
        if self.hasCBI():
            write_success = self.archiver.setArchiveComment( "" )
            if write_success:
                self.has_cbi = False
                self.cbi_md = None
            self.resetCache()
            return write_success
        return True

    def readCIX( self ):
        if self.cix_md is None:
            raw_cix = self.readRawCIX()
            if raw_cix is None or raw_cix == "":
                self.cix_md = GenericMetadata()
            else:
                self.cix_md = ComicInfoXml().metadataFromString( raw_cix )

            #validate the existing page list (make sure count is correct)
            if len ( self.cix_md.pages ) !=  0 :
                if len ( self.cix_md.pages ) != self.getNumberOfPages():
                    # pages array doesn't match the actual number of images we're seeing
                    # in the archive, so discard the data
                    self.cix_md.pages = []

            if len( self.cix_md.pages ) == 0:
                self.cix_md.setDefaultPageList( self.getNumberOfPages() )

        return self.cix_md

    def readRawCIX( self ):
        if not self.hasCIX():
            return None
        try:
            raw_cix = self.archiver.readArchiveFile( self.ci_xml_filename )
        except IOError:
            print  >> sys.stderr, u"Error reading in raw CIX!"
            raw_cix = ""
        return  raw_cix

    def writeCIX(self, metadata):

        if metadata is not None:
            self.applyArchiveInfoToMetadata( metadata, calc_page_sizes=True )
            cix_string = ComicInfoXml().stringFromMetadata( metadata )
            write_success = self.archiver.writeArchiveFile( self.ci_xml_filename, cix_string )
            if write_success:
                self.has_cix = True
                self.cix_md = metadata
            self.resetCache()
            return write_success
        else:
            return False

    def removeCIX( self ):
        if self.hasCIX():
            write_success = self.archiver.removeArchiveFile( self.ci_xml_filename )
            if write_success:
                self.has_cix = False
                self.cix_md = None
            self.resetCache()
            return write_success
        return True


    def hasCIX(self):
        if self.has_cix is None:

            if not self.seemsToBeAComicArchive():
                self.has_cix = False
            elif self.ci_xml_filename in self.archiver.getArchiveFilenameList():
                self.has_cix = True
            else:
                self.has_cix = False
        return self.has_cix


    def readCoMet( self ):
        if self.comet_md is None:
            raw_comet = self.readRawCoMet()
            if raw_comet is None or raw_comet == "":
                self.comet_md = GenericMetadata()
            else:
                self.comet_md = CoMet().metadataFromString( raw_comet )

            self.comet_md.setDefaultPageList( self.getNumberOfPages() )
            #use the coverImage value from the comet_data to mark the cover in this struct
            # walk through list of images in file, and find the matching one for md.coverImage
            # need to remove the existing one in the default
            if self.comet_md.coverImage is not None:
                cover_idx = 0
                for idx,f in enumerate(self.getPageNameList()):
                    if self.comet_md.coverImage == f:
                        cover_idx = idx
                        break
                if cover_idx != 0:
                    del (self.comet_md.pages[0]['Type'] )
                    self.comet_md.pages[ cover_idx ]['Type'] = PageType.FrontCover

        return self.comet_md

    def readRawCoMet( self ):
        if not self.hasCoMet():
            print >> sys.stderr, self.path, "doesn't have CoMet data!"
            return None

        try:
            raw_comet = self.archiver.readArchiveFile( self.comet_filename )
        except IOError:
            print >> sys.stderr, u"Error reading in raw CoMet!"
            raw_comet = ""
        return  raw_comet

    def writeCoMet(self, metadata):

        if metadata is not None:
            if not self.hasCoMet():
                self.comet_filename = self.comet_default_filename

            self.applyArchiveInfoToMetadata( metadata )
            # Set the coverImage value, if it's not the first page
            cover_idx = int(metadata.getCoverPageIndexList()[0])
            if cover_idx != 0:
                metadata.coverImage = self.getPageName( cover_idx )

            comet_string = CoMet().stringFromMetadata( metadata )
            write_success = self.archiver.writeArchiveFile( self.comet_filename, comet_string )
            if write_success:
                self.has_comet = True
                self.comet_md = metadata
            self.resetCache()
            return write_success
        else:
            return False

    def removeCoMet( self ):
        if self.hasCoMet():
            write_success = self.archiver.removeArchiveFile( self.comet_filename )
            if write_success:
                self.has_comet = False
                self.comet_md = None
            self.resetCache()
            return write_success
        return True

    def hasCoMet(self):
        if self.has_comet is None:
            self.has_comet = False
            if not self.seemsToBeAComicArchive():
                return self.has_comet

            #look at all xml files in root, and search for CoMet data, get first
            for n in self.archiver.getArchiveFilenameList():
                if ( os.path.dirname(n) == "" and
                    os.path.splitext(n)[1].lower() == '.xml'):
                    # read in XML file, and validate it
                    try:
                        data = self.archiver.readArchiveFile( n )
                    except:
                        data = ""
                        print >> sys.stderr, u"Error reading in Comet XML for validation!"
                    if CoMet().validateString( data ):
                        # since we found it, save it!
                        self.comet_filename = n
                        self.has_comet = True
                        break

            return self.has_comet



    def applyArchiveInfoToMetadata( self, md, calc_page_sizes=False):
        md.pageCount = self.getNumberOfPages()

        if calc_page_sizes:
            for p in md.pages:
                idx = int( p['Image'] )
                if pil_available:
                    if 'ImageSize' not in p or 'ImageHeight' not in p or 'ImageWidth' not in p:
                        data = self.getPage( idx )
                        if data is not None:
                            try:
                                im = Image.open(StringIO.StringIO(data))
                                w,h = im.size

                                p['ImageSize'] = str(len(data))
                                p['ImageHeight'] = str(h)
                                p['ImageWidth'] = str(w)
                            except IOError:
                                p['ImageSize'] = str(len(data))

                else:
                    if 'ImageSize' not in p:
                        data = self.getPage( idx )
                        p['ImageSize'] = str(len(data))



    def metadataFromFilename( self , parse_scan_info=True):

        metadata = GenericMetadata()

        fnp = FileNameParser()
        fnp.parseFilename( self.path )

        if fnp.issue != "":
            metadata.issue = fnp.issue
        if fnp.series != "":
            metadata.series = fnp.series
        if fnp.volume != "":
            metadata.volume = fnp.volume
        if fnp.year != "":
            metadata.year = fnp.year
        if fnp.issue_count != "":
            metadata.issueCount = fnp.issue_count
        if parse_scan_info:
            if fnp.remainder != "":
                metadata.scanInfo = fnp.remainder

        metadata.isEmpty = False

        return metadata

    def exportAsZip( self, zipfilename ):
        if self.archive_type == self.ArchiveType.Zip:
            # nothing to do, we're already a zip
            return True

        zip_archiver = ZipArchiver( zipfilename )
        return zip_archiver.copyFromArchive( self.archiver )
