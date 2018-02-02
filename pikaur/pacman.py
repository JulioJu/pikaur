from pprint import pformat

from .core import (
    CmdTaskWorker, SingleTaskExecutor, PackageUpdate,
    DataType, MultipleTasksExecutor,
    get_package_name_from_depend_line,
)


class PacmanTaskWorker(CmdTaskWorker):

    def __init__(self, args):
        super().__init__(
            [
                "pacman",
            ] + args
        )


class PacmanColorTaskWorker(PacmanTaskWorker):

    def __init__(self, args):
        super().__init__(
            [
                "--color=always",
            ] + args
        )


PACMAN_LIST_FIELDS = (
    'Conflicts With',
    'Replaces',
    'Depends On',
    'Provides',
    'Required By',
    'Optional For',
)


PACMAN_DICT_FIELDS = (
    'Optional Deps',
)


class PacmanPackageInfo(DataType):
    Name = None
    Version = None
    Description = None
    Architecture = None
    URL = None
    Licenses = None
    Groups = None
    Provides = None
    Depends_On = None
    Optional_Deps = None
    Conflicts_With = None
    Replaces = None
    Installed_Size = None
    Packager = None
    Build_Date = None
    Validated_By = None

    def __repr__(self):
        return f'<{self.__class__.__name__} "{self.Name}">'

    @property
    def all(self):
        return pformat(self.__dict__)

    @classmethod
    def parse_pacman_info(cls, lines):
        pkg = cls()
        field = value = None
        for line in lines:
            if line == '':
                yield pkg
                pkg = cls()
                continue
            if not line.startswith(' '):
                try:
                    _field, _value, *_args = line.split(': ')
                except ValueError:
                    print(line)
                    print(field, value)
                    raise()
                field = _field.rstrip()
                if _value == 'None':
                    value = None
                else:
                    if field in PACMAN_DICT_FIELDS:
                        value = {_value: None}
                    elif field in PACMAN_LIST_FIELDS:
                        value = _value.split()
                    else:
                        value = _value
                    if _args:
                        if field in PACMAN_DICT_FIELDS:
                            value = {_value: _args[0]}
                        else:
                            value = ': '.join([_value] + _args)
                            if field in PACMAN_LIST_FIELDS:
                                value = value.split()
            else:
                if field in PACMAN_DICT_FIELDS:
                    _value, *_args = line.split(': ')
                    value[_value] = _args[0] if _args else None
                elif field in PACMAN_LIST_FIELDS:
                    value += line.split()
                else:
                    value += line

            try:
                setattr(pkg, field.replace(' ', '_'), value)
            except TypeError:
                print(line)
                raise()


class RepoPackageInfo(PacmanPackageInfo):
    Repository = None
    Download_Size = None


class LocalPackageInfo(PacmanPackageInfo):
    Required_By = None
    Optional_For = None
    Install_Date = None
    Install_Reason = None
    Install_Script = None


class PackageDB():

    _repo_cache = None
    _local_cache = None
    _repo_dict_cache = None
    _local_dict_cache = None
    _repo_provided_cache = None
    _local_provided_cache = None

    repo = 'repo'
    local = 'local'

    @classmethod
    def get_dbs(cls):
        if not cls._repo_cache:
            print("Retrieving local pacman database...")
            results = MultipleTasksExecutor({
                cls.repo: PacmanTaskWorker(['-Si', ]),
                cls.local: PacmanTaskWorker(['-Qi', ]),
            }).execute()
            cls._repo_cache = list(RepoPackageInfo.parse_pacman_info(
                results[cls.repo].stdouts
            ))
            cls._local_cache = list(LocalPackageInfo.parse_pacman_info(
                results[cls.local].stdouts
            ))
        return {
            cls.repo: cls._repo_cache,
            cls.local: cls._local_cache
        }

    @classmethod
    def get_repo(cls):
        return cls.get_dbs()[cls.repo]

    @classmethod
    def get_local(cls):
        return cls.get_dbs()[cls.local]

    @classmethod
    def _get_dict(cls, dict_id):
        return {
            pkg.Name: pkg
            for pkg in PackageDB.get_dbs()[dict_id]
        }

    @classmethod
    def get_repo_dict(cls):
        if not cls._repo_dict_cache:
            cls._repo_dict_cache = cls._get_dict(cls.repo)
        return cls._repo_dict_cache

    @classmethod
    def get_local_dict(cls):
        if not cls._local_dict_cache:
            cls._local_dict_cache = cls._get_dict(cls.local)
        return cls._local_dict_cache

    @classmethod
    def _get_provided(cls, local):
        provided_pkg_names = []
        for pkg in (cls.get_local() if local == cls.local else cls.get_repo()):
            if pkg.Provides:
                for provided_pkg in pkg.Provides:
                    provided_pkg_names.append(
                        get_package_name_from_depend_line(provided_pkg)
                    )
        return provided_pkg_names

    @classmethod
    def get_repo_provided(cls):
        if not cls._repo_provided_cache:
            cls._repo_provided_cache = cls._get_provided(cls.repo)
        return cls._repo_provided_cache

    @classmethod
    def get_local_provided(cls):
        if not cls._local_provided_cache:
            cls._local_provided_cache = cls._get_provided(cls.local)
        return cls._local_provided_cache


def find_pacman_packages(packages, local=False):
    all_repo_packages = []
    for pkg in (PackageDB.get_local() if local else PackageDB.get_repo()):
        all_repo_packages.append(pkg.Name)

    pacman_packages = []
    not_found_packages = []
    for package_name in packages:
        if package_name not in all_repo_packages:
            not_found_packages.append(package_name)
        else:
            pacman_packages.append(package_name)
    return pacman_packages, not_found_packages


def find_repo_packages(packages):
    return find_pacman_packages(packages, local=False)


def find_local_packages(packages):
    return find_pacman_packages(packages, local=True)


def find_packages_not_from_repo():
    _repo_packages, not_found_packages = find_repo_packages(
        PackageDB.get_local_dict().keys()
    )
    return {
        pkg_name: PackageDB.get_local_dict()[pkg_name].Version
        for pkg_name in not_found_packages
    }


def find_repo_updates():
    result = SingleTaskExecutor(
        PacmanTaskWorker(['-Qu', ])
    ).execute()
    packages_updates_lines = result.stdouts
    repo_packages_updates = []
    for update in packages_updates_lines:
        pkg_name, current_version, _, new_version, *_ = update.split()
        repo_packages_updates.append(
            PackageUpdate(
                pkg_name=pkg_name,
                aur_version=new_version,
                current_version=current_version,
            )
        )
    return repo_packages_updates