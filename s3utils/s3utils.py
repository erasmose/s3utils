import os
import re
import boto
# from boto.s3.connection import S3Connection
from boto.s3.key import Key
from boto import connect_cloudfront
from shutil import rmtree
from collections import Iterable, OrderedDict
from functools import wraps  # deals with decorats shpinx documentation

try:
    from django.conf import settings
except:
    class settings(object):
        AWS_ACCESS_KEY_ID = ""
        AWS_SECRET_ACCESS_KEY = ""
        AWS_STORAGE_BUCKET_NAME = ""
        MEDIA_ROOT = ""
        MEDIA_ROOT_BASE = ""
        S3UTILS_DEBUG_LEVEL = 0

# Set default logging handler to avoid "No handler found" warnings.
import logging
try:  # Python 2.7+
    from logging import NullHandler
except ImportError:
    class NullHandler(logging.Handler):
        def emit(self, record):
            pass

logging.getLogger(__name__).addHandler(NullHandler())
logger = logging


def connectit(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        result = "Err"

        if not args[0].conn:
            args[0].connect()

        result = fn(*args, **kwargs)

        return result

    return wrapped

def connectit_cloudfront(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        result = "Err"

        if not args[0].conn_cloudfront:
            args[0].connect_cloudfront()

        result = fn(*args, **kwargs)

        return result

    return wrapped


class S3utils(object):

    def __init__(
        self, AWS_ACCESS_KEY_ID=getattr(settings, "AWS_ACCESS_KEY_ID", ""),
        AWS_SECRET_ACCESS_KEY=getattr(settings, "AWS_SECRET_ACCESS_KEY", ""),
        AWS_STORAGE_BUCKET_NAME=getattr(settings, "AWS_STORAGE_BUCKET_NAME", ""),
        MEDIA_ROOT=getattr(settings, "MEDIA_ROOT", ""),
        MEDIA_ROOT_BASE=getattr(settings, "MEDIA_ROOT_BASE", ""),
        S3UTILS_DEBUG_LEVEL=getattr(settings, "S3UTILS_DEBUG_LEVEL", 0),
    ):

        self.AWS_ACCESS_KEY_ID = AWS_ACCESS_KEY_ID
        self.AWS_SECRET_ACCESS_KEY = AWS_SECRET_ACCESS_KEY
        self.AWS_STORAGE_BUCKET_NAME = AWS_STORAGE_BUCKET_NAME
        self.MEDIA_ROOT = MEDIA_ROOT
        self.MEDIA_ROOT_BASE = MEDIA_ROOT_BASE
        self.S3UTILS_DEBUG_LEVEL = S3UTILS_DEBUG_LEVEL
        self.conn = None
        self.conn_cloudfront = None

        # setting the logging level based on S3UTILS_DEBUG_LEVEL
        try:
            if (S3UTILS_DEBUG_LEVEL == 0):
                logger.setLevel(logging.ERROR)
            else:
                logger.setLevel(logging.INFO)
        except AttributeError:
            pass

    def __del__(self):
        if self.conn:
            self.disconnect()

    def printv(self, msg):
        if self.S3UTILS_DEBUG_LEVEL:
            print(msg)
            logger.info(msg)

    def connect(self):
        "Establish the connection. This is normally done automatically."
        self.conn = boto.connect_s3(self.AWS_ACCESS_KEY_ID, self.AWS_SECRET_ACCESS_KEY, debug=self.S3UTILS_DEBUG_LEVEL)

        self.bucket = self.conn.get_bucket(self.AWS_STORAGE_BUCKET_NAME)

        self.k = Key(self.bucket)

    def disconnect(self):
        """
        Close the connection.

        This is normally done automatically but you need to
        use this to close the connection if you manually started the connection using the connect() method.
        """
        self.bucket.connection.connection.close()
        self.conn = None

    def connect_cloudfront(self):
        "Connect to cloud front which is more control than just S3. This is done automatically for you."
        self.conn_cloudfront = connect_cloudfront(self.AWS_ACCESS_KEY_ID, self.AWS_SECRET_ACCESS_KEY, debug=self.S3UTILS_DEBUG_LEVEL)

    @connectit
    def mkdir(self, target_folder):
        """
        Create a folder on S3.

        Examples
        --------
            >>> from s3utils import S3utils
            >>> s3utils = S3utils(
            ... AWS_ACCESS_KEY_ID = 'your access key',
            ... AWS_SECRET_ACCESS_KEY = 'your secret key',
            ... AWS_STORAGE_BUCKET_NAME = 'your bucket name',
            ... S3UTILS_DEBUG_LEVEL = 1,  #change it to 0 for less verbose
            ... )
            >>> s3utils.mkdir("path/to/my_folder")
            Making directory: path/to/my_folder
        """
        self.printv("Making directory: %s" % target_folder)
        self.k.key = re.sub(r"^/|/$", "", target_folder) + "/"
        self.k.set_contents_from_string('')
        self.k.close()

    def __cp_file(self, local_file, target_file, acl='public-read', del_after_upload=False, overwrite=True):
        """Copy a file to s3."""
        action_word = "moving" if del_after_upload else "copying"

        try:

            self.k.key = target_file  # setting the path (key) of file in the container
            # grabs the contents from local_file address. Note that it loads the whole file into memory
            self.k.set_contents_from_filename(local_file)
            logger.info("uploaded to s3: %s" % target_file)
            self.k.set_acl(acl)  # setting the file permissions
            self.k.close()  # not sure if it is needed. Somewhere I read it is recommended.

            self.printv("%s %s to %s" % (action_word, local_file, target_file))
            # if it is supposed to delete the local file after uploading
            if del_after_upload:
                try:
                    os.remove(local_file)
                except:
                    logger.error("Unable to delete the file: ", local_file, exc_info=True)

            return True

        except:
            logger.error("Error in writing to %s", target_file, exc_info=True)
            return False

    def cp(self, local_path, target_path, acl='public-read',
           del_after_upload=False, overwrite=True, invalidate=False):
        """
        Copy a file or folder from local to s3

        Parameters
        ----------

        local_path : string
            Path to file or folder. Or if you want to copy only the contents of folder, add /* at the end of folder name

        target_path : string
            Target path on S3 bucket.

        acl : string, optional
            File permissions on S3. Default is public-read

            options:
                - private: Owner gets FULL_CONTROL. No one else has any access rights.
                - public-read: Owners gets FULL_CONTROL and the anonymous principal is granted READ access.
                - public-read-write: Owner gets FULL_CONTROL and the anonymous principal is granted READ and WRITE access.
                - authenticated-read: Owner gets FULL_CONTROL and any principal authenticated as a registered Amazon S3 user is granted READ access


        del_after_upload : boolean, optional
            delete the local file after uploading. This is effectively like moving the file.
            You can use s3utils.mv instead of s3utils.cp to move files from local to S3.
            It basically sets this flag to True.
            default = False

        overwrite : boolean, optional
            overwrites files on S3 if set to True. Default is True

        invalidate : boolean, optional
            invalidates the CDN (a.k.a Distribution) cache if the file already exists on S3
            default = False
            Note that invalidation might take up to 15 minutes to take place. It is easier and faster to use cache buster
            to grab lastest version of your file on CDN than invalidation.



        Examples
        --------
            >>> from s3utils import S3utils
            >>> s3utils = S3utils(
            ... AWS_ACCESS_KEY_ID = 'your access key',
            ... AWS_SECRET_ACCESS_KEY = 'your secret key',
            ... AWS_STORAGE_BUCKET_NAME = 'your bucket name',
            ... S3UTILS_DEBUG_LEVEL = 1,  #change it to 0 for less verbose
            ... )
            >>> s3utils.cp("path/to/folder","/test/")
            copying /path/to/myfolder/test2.txt to test/myfolder/test2.txt
            copying /path/to/myfolder/test.txt to test/myfolder/test.txt
            copying /path/to/myfolder/hoho/photo.JPG to test/myfolder/hoho/photo.JPG
            copying /path/to/myfolder/hoho/haha/ff to test/myfolder/hoho/haha/ff

            >>> # When overwrite is set to False:
            >>> s3utils.cp("path/to/folder","/test/", overwrite=False)
            test/myfolder/test2.txt already exist. Not overwriting.
            test/myfolder/test.txt already exist. Not overwriting.
            test/myfolder/hoho/photo.JPG already exist. Not overwriting.
            test/myfolder/hoho/haha/ff already exist. Not overwriting.

            >>> # To overwrite the files on S3 and invalidate the CDN (cloudfront) cache so the new file goes on CDN:
            >>> s3utils.cp("path/to/folder","/test/", overwrite=True, invalidate=True)
            copying /path/to/myfolder/test2.txt to test/myfolder/test2.txt
            copying /path/to/myfolder/test.txt to test/myfolder/test.txt
            copying /path/to/myfolder/hoho/photo.JPG to test/myfolder/hoho/photo.JPG
            copying /path/to/myfolder/hoho/haha/ff to test/myfolder/hoho/haha/ff


        """

        result = None
        list_of_files = self.ls(folder=target_path, begin_from_file="", num=-1, get_grants=False, all_grant_data=False)

        # copying the contents of the folder and not folder itself
        if local_path.endswith("/*"):
            local_path = local_path[:-2]
            target_path = re.sub(r"^/|/$", "", target_path)  # Amazon S3 doesn't let the name to begin with /
        # copying folder too
        else:
            local_base_name = os.path.basename(local_path)

            local_path = re.sub(r"/$", "", local_path)
            target_path = re.sub(r"^/", "", target_path)

            if not target_path.endswith(local_base_name):
                target_path = os.path.join(target_path, local_base_name)

        if os.path.exists(local_path):

            result = self.__copy_path(local_path, target_path, acl, del_after_upload, overwrite, invalidate, list_of_files)

        else:
            result = {'file_does_not_exist': local_path}
            logger.error("trying to upload to s3 but file doesn't exist: %s" % local_path)

        return result

    @connectit
    def __copy_path(self, local_path, target_path, acl='public-read', del_after_upload=False, overwrite=True, invalidate=False, list_of_files=[]):
        files_to_be_invalidated = []
        failed_to_copy_files = set([])
        existing_files = set([])

        first_local_root = None

        # if it is a folder
        if os.path.isdir(local_path):

            for local_root, directories, files in os.walk(local_path):

                if not first_local_root:
                    first_local_root = local_root

                # if folder is not empty
                if files:
                    # iterating over the files in the folder
                    for a_file in files:
                        target_file = os.path.join(
                            target_path + local_root.replace(first_local_root, ""),
                            a_file
                        )

                        if overwrite or (not overwrite and target_file not in list_of_files):
                            success = self.__cp_file(
                                os.path.join(local_root, a_file),
                                target_file=target_file,
                                acl=acl,
                                del_after_upload=del_after_upload,
                                overwrite=overwrite,
                            )
                            if not success:
                                failed_to_copy_files.add(a_file)
                        else:
                            existing_files.add(a_file)
                            self.printv("%s already exist. Not overwriting." % target_file)

                        if overwrite and target_file in list_of_files and invalidate:
                            files_to_be_invalidated.append(target_file)

                # if folder is empty
                else:
                    target_file = target_path + local_root.replace(first_local_root, "") + "/"

                    if target_file not in list_of_files:
                        self.mkdir(target_file)

            if del_after_upload:
                rmtree(local_path)

        # if it is a file
        else:
            success = self.__cp_file(local_path, target_path, acl=acl, del_after_upload=del_after_upload, overwrite=overwrite)
            if not success:
                failed_to_copy_files.add(a_file)
            if overwrite and target_path in list_of_files and invalidate:
                files_to_be_invalidated.append(target_path)

        if invalidate and files_to_be_invalidated:
            self.invalidate(files_to_be_invalidated)

        items = ('failed_to_copy_files', 'existing_files')
        local_vars = locals()
        result = {}
        for i in items:
            val = local_vars.get(i)
            if val:
                result[i] = val

        result = None if result == {} else result
        return result

    def mv(self, local_file, target_file, acl='public-read', overwrite=True, invalidate=False):
        """
        Move the file to the S3 and deletes the local copy

        It is basically s3utils.cp that has del_after_upload=True

        Examples
        --------

            >>> from s3utils import S3utils
            >>> s3utils = S3utils(
            ... AWS_ACCESS_KEY_ID = 'your access key',
            ... AWS_SECRET_ACCESS_KEY = 'your secret key',
            ... AWS_STORAGE_BUCKET_NAME = 'your bucket name',
            ... S3UTILS_DEBUG_LEVEL = 1,  #change it to 0 for less verbose
            ... )
            >>> s3utils.mv("path/to/folder","/test/")
            moving /path/to/myfolder/test2.txt to test/myfolder/test2.txt
            moving /path/to/myfolder/test.txt to test/myfolder/test.txt
            moving /path/to/myfolder/hoho/photo.JPG to test/myfolder/hoho/photo.JPG
            moving /path/to/myfolder/hoho/haha/ff to test/myfolder/hoho/haha/ff

        """
        self.cp(local_file, target_file, acl=acl, del_after_upload=True, overwrite=overwrite, invalidate=invalidate)

    @connectit
    def cp_cropduster_image(self, the_image_path, del_after_upload=False, overwrite=False, invalidate=False):
        """Deal with cropduster images saving to S3"""
        # logger.info("CKeditor the_image_path: %s" % the_image_path)

        local_file = os.path.join(settings.MEDIA_ROOT, the_image_path)

        # only try to upload things if the origin cropduster file exists (so it is not already uploaded to the CDN)
        if os.path.exists(local_file):

            the_image_crops_path = os.path.splitext(the_image_path)[0]
            the_image_crops_path_full_path = os.path.join(settings.MEDIA_ROOT, the_image_crops_path)

            self.cp(local_path=local_file,
                    target_path=os.path.join(settings.MEDIA_ROOT_BASE, the_image_path),
                    del_after_upload=del_after_upload,
                    overwrite=overwrite,
                    invalidate=invalidate,
                    )

            self.cp(local_path=the_image_crops_path_full_path + "/*",
                    target_path=os.path.join(settings.MEDIA_ROOT_BASE, the_image_crops_path),
                    del_after_upload=del_after_upload,
                    overwrite=overwrite,
                    invalidate=invalidate,
                    )

    def __get_grants(self, target_file, all_grant_data):
        """
        Return grant permission, grant owner, grant owner email and grant id  as a list.
        It needs you to set k.key to a key on amazon (file path) before running this.
        note that Amazon returns a list of grants for each file.

        options:
            - private: Owner gets FULL_CONTROL. No one else has any access rights.
            - public-read: Owners gets FULL_CONTROL and the anonymous principal is granted READ access.
            - public-read-write: Owner gets FULL_CONTROL and the anonymous principal is granted READ and WRITE access.
            - authenticated-read: Owner gets FULL_CONTROL and any principal authenticated as a registered Amazon S3 user is granted READ access

        """
        self.k.key = target_file

        the_grants = self.k.get_acl().acl.grants

        grant_list = []

        for grant in the_grants:
            if all_grant_data:
                grant_list.append(
                    {"permission": grant.permission, "name": grant.display_name, "email": grant.email_address, "id": grant.id})
            else:
                grant_list.append({"permission": grant.permission, "name": grant.display_name})

        return grant_list

    @connectit
    def chmod(self, target_file, acl='public-read'):
        """
        sets permissions for a file on S3

        Parameters
        ----------

        target_file : string
            Path to file on S3

        acl : string, optional
            File permissions on S3. Default is public-read

            options:
                - private: Owner gets FULL_CONTROL. No one else has any access rights.
                - public-read: Owners gets FULL_CONTROL and the anonymous principal is granted READ access.
                - public-read-write: Owner gets FULL_CONTROL and the anonymous principal is granted READ and WRITE access.
                - authenticated-read: Owner gets FULL_CONTROL and any principal authenticated as a registered Amazon S3 user is granted READ access


        Examples
        --------

            >>> from s3utils import S3utils
            >>> s3utils = S3utils(
            ... AWS_ACCESS_KEY_ID = 'your access key',
            ... AWS_SECRET_ACCESS_KEY = 'your secret key',
            ... AWS_STORAGE_BUCKET_NAME = 'your bucket name',
            ... S3UTILS_DEBUG_LEVEL = 1,  #change it to 0 for less verbose
            ... )
            >>> s3utils.chmod("path/to/file","private")


        """
        self.k.key = target_file  # setting the path (key) of file in the container
        self.k.set_acl(acl)  # setting the file permissions
        self.k.close()

    @connectit
    def ls(self, folder="", begin_from_file="", num=-1, get_grants=False, all_grant_data=False):
        """
        gets the list of file names (keys) in a s3 folder

        Parameters
        ----------

        folder : string
            Path to file on S3

        num: integer, optional
            number of results to return, by default it returns all results.

        begin_from_file: string, optional
            which file to start from on S3.
            This is usedful in case you are iterating over lists of files and you need to page the result by
            starting listing from a certain file and fetching certain num (number) of files.


        Examples
        --------

            >>> from s3utils import S3utils
            >>> s3utils = S3utils(
            ... AWS_ACCESS_KEY_ID = 'your access key',
            ... AWS_SECRET_ACCESS_KEY = 'your secret key',
            ... AWS_STORAGE_BUCKET_NAME = 'your bucket name',
            ... S3UTILS_DEBUG_LEVEL = 1,  #change it to 0 for less verbose
            ... )
            >>> print(s3utils.ls("test/"))
            {u'test/myfolder/', u'test/myfolder/em/', u'test/myfolder/hoho/', u'test/myfolder/hoho/.DS_Store', u'test/myfolder/hoho/haha/', u'test/myfolder/hoho/haha/ff', u'test/myfolder/hoho/haha/photo.JPG'}

        """
        # S3 object key can't start with /
        folder = re.sub(r"^/", "", folder)

        bucket_files = self.bucket.list(prefix=folder, marker=begin_from_file)

        # in case listing grants
        if get_grants:
            list_of_files = OrderedDict()
            for (i, v) in enumerate(bucket_files):
                file_info = {v.name: self.__get_grants(v.name, all_grant_data)}
                list_of_files.update(file_info)
                if i == num:
                    break

        else:
            list_of_files = set([])
            for (i, v) in enumerate(bucket_files):
                list_of_files.add(v.name)
                if i == num:
                    break

        return list_of_files

    def ll(self, folder="", begin_from_file="", num=-1, all_grant_data=False):
        """
        Get the list of files and permissions from S3

        Parameters
        ----------

        folder : string
            Path to file on S3

        num: integer, optional
            number of results to return, by default it returns all results.

        begin_from_file : string, optional
            which file to start from on S3.
            This is usedful in case you are iterating over lists of files and you need to page the result by
            starting listing from a certain file and fetching certain num (number) of files.

        all_grant_data : Boolean, optional
            More detailed file permission data will be returned.

        Examples
        --------

            >>> from s3utils import S3utils
            >>> s3utils = S3utils(
            ... AWS_ACCESS_KEY_ID = 'your access key',
            ... AWS_SECRET_ACCESS_KEY = 'your secret key',
            ... AWS_STORAGE_BUCKET_NAME = 'your bucket name',
            ... S3UTILS_DEBUG_LEVEL = 1,  #change it to 0 for less verbose
            ... )
            >>> import json
            >>> # We use json.dumps to print the results more readable:
            >>> my_folder_stuff = s3utils.ll("/test/")
            >>> print(json.dumps(my_folder_stuff, indent=2))
            {
              "test/myfolder/": [
                {
                  "name": "owner's name",
                  "permission": "FULL_CONTROL"
                }
              ],
              "test/myfolder/em/": [
                {
                  "name": "owner's name",
                  "permission": "FULL_CONTROL"
                }
              ],
              "test/myfolder/hoho/": [
                {
                  "name": "owner's name",
                  "permission": "FULL_CONTROL"
                }
              ],
              "test/myfolder/hoho/.DS_Store": [
                {
                  "name": "owner's name",
                  "permission": "FULL_CONTROL"
                },
                {
                  "name": null,
                  "permission": "READ"
                }
              ],
              "test/myfolder/hoho/haha/": [
                {
                  "name": "owner's name",
                  "permission": "FULL_CONTROL"
                }
              ],
              "test/myfolder/hoho/haha/ff": [
                {
                  "name": "owner's name",
                  "permission": "FULL_CONTROL"
                },
                {
                  "name": null,
                  "permission": "READ"
                }
              ],
              "test/myfolder/hoho/photo.JPG": [
                {
                  "name": "owner's name",
                  "permission": "FULL_CONTROL"
                },
                {
                  "name": null,
                  "permission": "READ"
                }
              ],
            }

        """
        return self.ls(folder=folder, begin_from_file=begin_from_file, num=num, get_grants=True, all_grant_data=all_grant_data)

    @connectit_cloudfront
    def invalidate(self, files_to_be_invalidated):
        """
        Invalidate the CDN (distribution) cache for a certain file of files. This might take up to 15 minutes to be effective.

        You can check for the invalidation status using check_invalidation_request.

        Examples
        --------

            >>> from s3utils import S3utils
            >>> s3utils = S3utils(
            ... AWS_ACCESS_KEY_ID = 'your access key',
            ... AWS_SECRET_ACCESS_KEY = 'your secret key',
            ... AWS_STORAGE_BUCKET_NAME = 'your bucket name',
            ... S3UTILS_DEBUG_LEVEL = 1,  #change it to 0 for less verbose
            ... )
            >>> aa = s3utils.invalidate("test/myfolder/hoho/photo.JPG")
            >>> print(aa)
            ('your distro id', u'your request id')
            >>> invalidation_request_id = aa[1]
            >>> bb = s3utils.check_invalidation_request(*aa)
            >>> for inval in bb:
            ...     print('Object: %s, ID: %s, Status: %s' % (inval, inval.id, inval.status))


        """
        if not isinstance(files_to_be_invalidated, Iterable):
            files_to_be_invalidated = (files_to_be_invalidated,)

        # Your CDN is called distribution on Amazaon. And you can have more than one distro
        all_distros = self.conn_cloudfront.get_all_distributions()

        for distro in all_distros:
            invalidation_request = self.conn_cloudfront.create_invalidation_request(distro.id, files_to_be_invalidated)

        return (distro.id, invalidation_request.id)

    @connectit_cloudfront
    def check_invalidation_request(self, distro, request_id):

        return self.conn_cloudfront.get_invalidation_requests(distro, request_id)
