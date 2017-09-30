'''
 This file is part of pycotools.

 pycotools is free software: you can redistribute it and/or modify
 it under the terms of the GNU Lesser General Public License as published by
 the Free Software Foundation, either version 3 of the License, or
 (at your option) any later version.

 pycotools is distributed in the hope that it will be useful,
 but WITHOUT ANY WARRANTY; without even the implied warranty of
 MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 GNU Lesser General Public License for more details.

 You should have received a copy of the GNU Lesser General Public License
 along with pycotools.  If not, see <http://www.gnu.org/licenses/>.




 Object:
 
 PEAnalysis provies a number of convenient classes for visualizing 
 and analysing parameter estimation data. The module can be used with 
 any PE data regardless of origin but has been developed with copasi in 
 mind. 
  


 $Author: Ciaran Welsh
 $Date: 12-09-2016 
 Time:  20:33


Features to include:
    PCA for dimensionality reduction of the PE data. Identify component with most variance 
    
    Create class for computing model selection criteria
        AIC/BIC
        
        
    I could begin giving my python classes things like iteration capabilities or
    getters...


'''


##TODO Fix plot_kwargs
##TODO fix parameter estimation ensembles
import contextlib
import string
import pandas 
import matplotlib.pyplot as plt
import scipy 
import os
import matplotlib
import itertools
import tasks,errors, misc, model
import seaborn 
import logging
from subprocess import check_call,Popen
import glob
import re
import numpy
from mixin import Mixin, mixin
from textwrap import wrap
from sklearn.decomposition import PCA
from sklearn import linear_model
from sklearn import model_selection
LOG=logging.getLogger(__name__)
import _base

SEABORN_OPTIONS = {'context':'poster',
                   'font_scale':2}

seaborn.set_context(context=SEABORN_OPTIONS['context'], font_scale=SEABORN_OPTIONS['font_scale'])


class PlotKwargs(object):
    def plot_kwargs(self):
        plot_kwargs = {
            'linestyle': '-',
            'marker': 'o',
            'linewidth': 5,
            'markersize': 12,
        }
        return plot_kwargs

class SaveFigMixin(Mixin):
    """
    save figure to a directory and filename.
    create teh directory if it doesn't exist.
    """
    @staticmethod
    def save_figure(directory, filename, dpi=300):
        if not os.path.isdir(directory):
            os.mkdir(directory)
        plt.savefig(filename, dpi=dpi, bbox_inches='tight')


@mixin(_base.UpdatePropertiesMixin)
class TruncateData(object):
    '''
    Parameter estimation data in systems biology usually have runs which fall
    into a local minima. Usually a user wants to remove these runs from further
    analysis. TruncateData does this and provides two modes to do so. A useful
    indication of where to truncate the data is to look at the plot produced
    by the EvaluateOptimizationPerformance class and the histograms/boxplots/
    profile likelihoods for your specific optimization problem.

    Args:
        data:
            The parameter estiamtion data for truncation. This is a pandas dataframe.

    kwargs:
        mode:
            Two modes accepted. When set to 'percent' take xth percentile of
            data. when set to 'below_x', truncate data below the value x. Pay
            attention to whether you are in log10 mode or not.

        x:
            Either xth percentive,  value to truncate data below or list specifying an index of best fit
    '''

    def __init__(self, data, mode='percent', theta=100, log10=False):
        self.data = data
        self.mode = mode
        self.theta = theta
        self.log10 = log10
        assert self.mode in ['below_theta', 'percent', 'ranks']

        self.data = self.truncate()

    def below_theta(self):
        assert self.data.shape[0] != 0, 'There are no data with RSS below {}. Choose a higher number'.format(self.theta)
        return self.data[self.data['RSS'] < self.theta]

    def top_theta_percent(self):
        '''
        get top theta percent data.
        Defulat= 100 = all data
        '''
        if self.theta > 100 or self.theta < 1:
            raise errors.InputError('{} should be between 0 and 100')
        theta_quantile = int(numpy.round(self.data.shape[0] * (float(self.theta) / 100.0)))
        return self.data.iloc[:theta_quantile]

    def ranks(self):
        return self.data.iloc[self.theta]

    def truncate(self):
        if self.mode == 'below_theta':
            return self.below_theta()  # self.data
        elif self.mode == 'percent':
            return self.top_theta_percent()
        elif self.mode == 'ranks':
            return self.ranks()

class ParseMixin(Mixin):
    @staticmethod
    def parse(cls, log10):
        """
        Use parse class to get the data
        :return:
        """
        return Parse(cls, log10=log10).data


class TruncateDataMixin(Mixin):

    @staticmethod
    def truncate(data, mode, theta):
        """
        mixin method interface to truncate data
        """
        df = TruncateData(data,
                            mode=mode,
                            theta=theta).data
        return df

class CreateResultsDirectoryMixin(Mixin):
    @staticmethod
    def create_directory(results_directory):
        """
        create directory for results and switch to it
        :param results_directory:
        :return:
        """
        if not os.path.isdir(results_directory):
            os.makedirs(results_directory)
        os.chdir(results_directory)
        return results_directory


class Parse(object):
    def __init__(self, cls_instance, log10=False):
        self.cls_instance = cls_instance
        self.log10 = log10
        accepted_types = [tasks.TimeCourse,
                          tasks.Scan,
                          tasks.ParameterEstimation,
                          tasks.MultiParameterEstimation]

        if type(self.cls_instance) not in accepted_types:
            raise errors.InputError('{} not in {}'.format(
                self.cls_instance,
                accepted_types)
            )

        if isinstance(self.cls_instance, tasks.Scan):
            LOG.debug('type cls instance --> {}'.format(type(self.cls_instance)))
            LOG.debug('type cls instance. scan type--> {}'.format(self.cls_instance.scan_type))

            ## '1' is copasi code name for a scan
            if self.cls_instance.scan_type != '1':
                raise errors.InputError(
                    'plotting functions are only available for scans (not repeat or random distributions)'
                )

        self.data = self.parse()


    def parse(self):
        """
        determine class type of self.cls_instance
        and call the appropirate method for
        parsing the data type
        :return:
        """

        if isinstance(self.cls_instance, tasks.TimeCourse):
            data = self.parse_timecourse()

        elif type(self.cls_instance) == tasks.ParameterEstimation:
            data = self.parse_parameter_estmation()

        elif type(self.cls_instance) == tasks.MultiParameterEstimation:
            data = self.parse_multi_parameter_estimation(self.cls_instance)

        if self.log10:
            data = numpy.log10(data)
            return data
        else:
            return data\

    def parse_timecourse(self):
        """
        read time course data into pandas dataframe. Remove
        copasi generated square brackets around the variables
        :return: pandas.DataFrame
        """

        df = pandas.read_csv(self.cls_instance.report_name, sep='\t')
        headers = [re.findall('(Time)|\[(.*)\]', i)[0] for i in list(df.columns)]
        time = headers[0][0]
        headers = [i[1] for i in headers]
        headers[0] = time
        df.columns = headers
        return df

    def parse_scan(self):
        """
        read scan data into pandas Dataframe.
        :return: pandas.DataFrame
        """
        df = pandas.read_csv(
            self.cls_instance.report_name,
            sep='\t',
            skip_blank_lines=False,
        )
        # names = []
        # d = {names[i]: x.dropna() for i, x in df.groupby(df[0].isnull().cumsum())}
        return NotImplementedError('scan plotting features are not yet implemented')


    def parse_parameter_estmation(self):
        """

        :return:
        """
        df = pandas.read_csv(
            self.cls_instance.report_name,
            sep='\t', header=None
        )
        data = df.drop(df.columns[0], axis=1)
        width = data.shape[1]
        ## remove the extra bracket
        data[width] = data[width].str[1:]
#        num = data.shape[0]
        names = self.cls_instance.model.fit_item_order+['RSS']
        data.columns = names
        os.remove(self.cls_instance.report_name)
        data.to_csv(self.cls_instance.report_name,
                    sep='\t',
                    index=False)
        return data

    @staticmethod
    def parse_multi_parameter_estimation(cls_instance, folder=None):
        """
        Results come without headers - parse the results
        give them the proper headers then overwrite the file again
        :param cls_instance: instance of MultiParameterEstiamtion
        :param folder: afternative folder to parse from. Useful for tests
        :return:
        """
        ##set default
        if folder == None:
            folder = cls_instance.results_directory
        d = {}
        for report_name in glob.glob(folder+r'/*'):
            report_name = os.path.abspath(report_name)
            if os.path.isfile(report_name) !=True:
                raise errors.FileDoesNotExistError('"{}" does not exist'.format(report_name))

            try:
                data = pandas.read_csv(report_name,
                                       sep='\t', header=None, skiprows=[0])
            except:
                LOG.warning('No Columns to parse from file. {} is empty. Returned None'.format(
                    report_name))
                return None
            bracket_columns = data[data.columns[[0,-2]]]
            if bracket_columns.iloc[0].iloc[0] != '(':
                data = pandas.read_csv(report_name, sep='\t')
                d[report_name] = data
            else:
                data = data.drop(data.columns[[0,-2]], axis=1)
                data.columns = range(data.shape[1])
                ### parameter of interest has been removed.
                names = cls_instance.model.fit_item_order+['RSS']
                if cls_instance.model.fit_item_order == []:
                    raise errors.SomethingWentHorriblyWrongError('Parameter Estimation task is empty')
                if len(names) != data.shape[1]:
                    raise errors.SomethingWentHorriblyWrongError('length of parameter estimation data does not equal number of parameters estimated')

                if os.path.isfile(report_name):
                    os.remove(report_name)
                data.columns = names
                data.to_csv(report_name, sep='\t', index=False)
                d[report_name] = data
        df = pandas.concat(d)
        columns = df.columns
        ## reindex, drop and sort by RSS
        df = df.reset_index().drop(['level_0', 'level_1'], axis=1).sort_values(by='RSS')

        return df.reset_index(drop=True)


@mixin(_base.UpdatePropertiesMixin)
@mixin(SaveFigMixin)
@mixin(ParseMixin)
@mixin(CreateResultsDirectoryMixin)
class PlotTimeCourse(PlotKwargs):
    def __init__(self, cls, **kwargs):
        super(PlotTimeCourse, self).__init__()
        self.cls = cls
        self.kwargs = kwargs

        self.default_properties = {
            'x': 'time',
            'y': [i.name for i in self.cls.model.metabolites] + [i.name for i in self.cls.model.global_quantities],
            'log10': False,
            'separate': True,
            'savefig': False,
            'results_directory': None,
            'title': 'TimeCourse',
            'xlabel': None,
            'ylabel': None,
            'show': False,
            'filename': None,
            'dpi': 300,
        }
        self.default_properties.update(self.plot_kwargs())
        for i in kwargs.keys():
            assert i in self.default_properties.keys(),'{} is not a keyword ' \
                                                       'argument for PlotTimeCourse'.format(i)
        self.kwargs = self.default_properties
        self.default_properties.update(kwargs)
        self.default_properties.update(self.plot_kwargs())
        self.update_properties(self.default_properties)
        self._do_checks()

        self.data = self.parse(self.cls, self.log10)
        self.plot()

    def __str__(self):
        """

        :return:
        """
        return "PlotTimeCourse(x='{}', y={}, log10={}, separate={}, savefig={}, results_directory='{}'".format(
            self.x, self.y, self.log10,
            self.separate, self.savefig,
            self.results_directory
        )

    def _do_checks(self):
        """

        :return:
        """
        if not isinstance(self.cls, tasks.TimeCourse):
            raise errors.InputError(
                'PlotTimeCourse class expects an instance of'
                ' tasks.TimeCourse as first argument. '
                'Got {} instead'.format(type(self.cls)))

        if not isinstance(self.x, str):
            raise errors.InputError('x should be a string. Got {}'.format(type(self.x)))

        if self.y is not None:
            if not isinstance(self.y, (str, list)):
                raise errors.InputError('y should be a string or list of strings. Got {}'.format(type(self.y)))

        bool_list = [self.separate,
                     self.savefig]
        for i in bool_list:
            if not isinstance(i, bool):
                raise errors.InputError('{} argument should be boolean. Got {}'.format(i, type(i)))

        if self.results_directory is None:
            self.results_directory = os.path.join(
                self.cls.model.root, 'TimeCourseGraphs'
            )

        if self.x.lower() == 'time':
            self.xlabel = "Time ({})".format(self.cls.model.time_unit)

        if self.xlabel is None:
            self.xlabel = self.x

        if self.ylabel is None:
            self.ylabel = 'Concentration ({})'.format(self.cls.model.quantity_unit)

        if self.savefig and (self.separate is False) and (self.filename is None):
            self.filename = 'TimeCourse.jpeg'
            LOG.warning('filename is None. Setting default filename to {}'.format(self.filename))

    def plot(self):
        """

        :return:
        """
        if self.y == None:
            self.y == self.data.keys()

        if isinstance(self.y, str):
            self.y = [self.y]


        for i in self.y:
            if i not in self.data.keys():
                raise errors.InputError('{} not in {}'.format(i, self.data.keys()))

        if self.x == 'time':
            self.x = 'Time'
        if self.x not in self.data.keys():
            raise errors.InputError('{} not in {}'.format(self.x, self.data.keys()))

        figures = []
        if not self.separate:
            fig = plt.figure()
            figures.append(fig)

        # self.create_results_directory(self.results_directory)

        for y_var in self.y:
            if self.separate:
                fig = plt.figure()
                figures.append(fig)
            y = self.data[y_var]
            x = self.data[self.x]
            plt.plot(x, y, label=y_var)
            plt.legend()
            plt.title(self.title)
            plt.xlabel(self.xlabel)
            plt.ylabel(self.ylabel)
            if self.savefig:
                if self.separate:
                    fle = os.path.join(self.results_directory, '{}.jpeg'.format(y_var))
                    fig.savefig(fle, dpi=self.dpi, bbox_inches='tight')
                else:
                    fle = os.path.join(self.results_directory, self.filename)
                    fig.savefig(fle, dpi=self.dpi, bbox_inches='tight')

        if self.show:
            plt.show()
        return figures

@mixin(_base.UpdatePropertiesMixin)
@mixin(SaveFigMixin)
@mixin(ParseMixin)
@mixin(CreateResultsDirectoryMixin)
class PlotScan(object):
    def __init__(self, cls, **kwargs):
        self.cls = cls
        self.kwargs = kwargs

        self.default_properties = {
            'x': 'time',
            'y': [i.name for i in self.cls.model.metabolites],
            'log10': False,
            'separate': False,
            'savefig': False,
            'results_directory': None,
            'title': 'TimeCourse',
            'xlabel': None,
            'ylabel': None,
            'show': False,
            'filename': None,
            'dpi': 300,
        }

        for i in kwargs.keys():
            assert i in self.default_properties.keys(), '{} is not a keyword argument for Boxplot'.format(i)
        self.kwargs = self.default_properties
        self.default_properties.update(kwargs)
        self.update_properties(self.default_properties)
        self._do_checks()

        raise NotImplementedError

        self.data = self.parse(self.cls, self.log10)

    def __str__(self):
        """

        :return:
        """
        return "PlotScan(x='{}', y={}, log10={}, separate={}, savefig={}, results_directory='{}'".format(
            self.x, self.y, self.log10,
            self.separate, self.savefig,
            self.results_directory
        )

@mixin(_base.UpdatePropertiesMixin)
@mixin(SaveFigMixin)
@mixin(ParseMixin)
@mixin(CreateResultsDirectoryMixin)
class PlotParameterEstimation(PlotKwargs):
    """
    Create new folder for each experiment
    defined under the sub directory of results_directory
    """
    def __init__(self, cls, **kwargs):
        self.cls = cls
        self.kwargs = kwargs
        self.plot_kwargs = self.plot_kwargs()


        default_y = [i.name for i in self.cls.model.metabolites] + [i.name for i in self.cls.model.global_quantities]
        self.default_properties = {
            'x': None,
            'y': None,
            'log10': False,
            'savefig': False,
            'results_directory': None,
            'title': 'TimeCourse',
            'xlabel': None,
            'ylabel': None,
            'show': False,
            'filename': None,
            'dpi': 300,
        }
        self.default_properties.update(self.plot_kwargs)
        for i in kwargs.keys():
            assert i in self.default_properties.keys(),'{} is not a keyword argument for Boxplot'.format(i)
        self.kwargs = self.default_properties
        self.default_properties.update(kwargs)
        self.default_properties.update(self.plot_kwargs)
        self.update_properties(self.default_properties)
        self._do_checks()

        self.data = self.parse(self.cls, self.log10)
        self.cls.model = self.update_parameters()


    def __str__(self):
        """

        :return:
        """
        return "PlotParameterEstimation(x='{}', y={}, savefig={}, results_directory='{}'".format(
            self.x, self.y, self.savefig,
            self.results_directory
        )

    def _do_checks(self):


        if not isinstance(self.cls, tasks.ParameterEstimation):
            raise errors.InputError('first argument should be ParameterEstimation calss. Got {}'.format(type(self.cls)))

        if self.results_directory == None:
            self.results_directory = os.path.join(self.cls.model.root,
                                                  'ParameterEstimationPlots')


    def update_parameters(self):
        """
        Use the InsertParameters class to insert estimated
        parameters into the model
        :return: Model
        """
        I = model.InsertParameters(self.cls.model, df=self.data)
        return I.model

    def create_directories(self):
        """
        create a directory in project root called result_directory
        create subfolders with name of experiments
        :return: dict
        """
        directories = {}
        for fle in self.cls.experiment_files:
            _, fle = os.path.split(fle)
            directories[fle] = os.path.join(self.results_directory, fle[:-4])
            if not os.path.isdir(directories[fle]):
                os.makedirs(directories[fle])
        return directories

    def read_experimental_data(self):
        """
        read the experimental data in order to figure
        out how long a time course we need to simulate
        with the new parameters
        :return:
        """
        dct = {}
        for i in self.cls.experiment_files:
            dct[i] = pandas.read_csv(i, sep='\t')
        return dct

    def get_time(self):
        """
        get dict of experiments and max time
        :return:
        """
        dct = {}
        data_dct = self.read_experimental_data()
        for i in data_dct:
            dct[i] = data_dct[i]['Time'].max()
        return dct

    def simulate_time_course(self):
        """
        simulate a timecourse for each experiment
        which may have different simulation lengths
        :return:
        """
        time_dct = self.get_time()
        d = {}
        step_size = 1
        for i in time_dct:
            TC = tasks.TimeCourse(self.cls.model, end=time_dct[i],
                             step_size=step_size, intervals=time_dct[i]/step_size)
            d[i] = self.parse(TC, log10=False)
        return d

    def plot(self):
        """
        plot experimental data versus best parameter sets
        :return:
        """
        if self.y == None:
            self.y = self.read_experimental_data().values()[0].keys()
            self.y = [i for i in self.y if i != 'Time']
        exp_data = self.read_experimental_data()
        sim_data = self.simulate_time_course()


        for exp in exp_data:
            for sim in sim_data:
                if exp == sim:
                    for key in self.y:
                        plt.figure()
                        plt.plot(
                            exp_data[exp]['Time'], exp_data[exp][key],
                            label='Exp', linestyle=self.linestyle,
                            marker=self.marker, linewidth=self.linewidth,
                            markersize=self.markersize
                        )
                        plt.plot(
                            sim_data[sim]['Time'], sim_data[sim][key],
                            label='Sim', linestyle=self.linestyle,
                            marker=self.marker, linewidth=self.linewidth,
                            markersize=self.markersize)
                        plt.legend(loc='best')
                        if self.savefig:
                            dirs = self.create_directories()
                            exp_key = os.path.split(exp)[1]
                            fle = os.path.join(dirs[exp_key], '{}.jpeg'.format(key))
                            plt.savefig(fle, dpi=self.dpi, bbox_inches='tight')
        if self.show:
            plt.show()


















# class Parse2():
#     '''
#     parse parameter estimation data from file
#
#     Args:
#         results_path:
#             Absolute path to file or folder of files containing parameter
#             estimation data.
#
#     kwargs:
#         use_pickle:
#             Allow one to overwrite the pickle file automatically
#             produced for speed. Default=False
#     '''
#     def __init__(self,results_path, sep='\t', log10=False, type='multi_parameter_estimation'):
#         self.results_path = results_path
#         self.log10 = log10
#         self.sep = sep
#         self.type = type
#
#         valid_types = ['multi_parameter_estimation',
#                        'parameter_estimation',
#                        'timecourse',
#                        'scan']
#         # if self.type not in valid_types:
#         #     raise errors.InputError('{} not a valid type --> {}'.format(self.type, valid_types))
#         #
#         # if self.type == 'multi_parameter_estimation':
#         #     pass
#
#
#         # if self.log10:
#         #     self.data = numpy.log10(self._read_data())
#         # else:
#         #     self.data = self._read_data()
#         #
#         # self.data = self.data.sort_values(by='RSS', ascending=True)
#
#
#     def read_time_course_data(self):
#         pass
#
#     def format_multi_pe_data(self, model):
#         """
#         Copasi output does not have headers. This function
#         gives PE data output headers based on the parameter
#         estimation configuration
#         :return: list. Path to report files
#         """
#         print model
#         # try:
#         #     cps_keys = self.sub_copasi_files.keys()
#         # except AttributeError:
#         #     self.setup()
#         #     cps_keys = self.sub_copasi_files.keys()
#         # report_keys = self.report_files.keys()
#         # for i in range(len(self.report_files)):
#         #     try:
#         #         FormatPEData(self.sub_copasi_files[cps_keys[i]], self.report_files[report_keys[i]],
#         #                  report_type='multi_parameter_estimation')
#         #     except errors.InputError:
#         #         LOG.warning('{} is empty. Cannot parse. Skipping this file'.format(self.report_files[report_keys[i]]))
#         #         continue
#         # return self.report_files
#
#
#
#     def _read_data(self):
#         """
#
#         """
#         if os.path.isfile(self.results_path):
#             return self.read_PE_data_file(self.results_path)
#         elif os.path.isdir(self.results_path):
#             return self.read_PE_data_folder()
#         else:
#             raise errors.InputError('results_path argument should be a PE data file or folder of identically formed PE data files')
#
#
#     def read_PE_data_file(self, path):
#         """
#
#         """
#         ## check that the data has been formatted before entry into PEAnalysis module
#         try:
#             data = pandas.read_csv(path, sep='\t', header=None, skiprows=0)
#         except pandas.parser.CParserError:
#             LOG.warning('Cannot parse data from {}'.format(path))
#             return None
#         if data.shape == (1,2):
#             if data.iloc[0][0] == 'TaskList[Parameter Estimation].(Problem)Parameter Estimation.Best Parameters':
#                 if data.iloc[0][1] == 'TaskList[Parameter Estimation].(Problem)Parameter Estimation.Best Value':
#                     LOG.warning('Data file "{}" only contains nothing. File ignored'.format(path))
#                     return None
#         for i in data.iloc[0]:
#             if i=='(':
#                 raise errors.InputError('Brackets are still in your data file. Ensure you\'ve properly formatted PE data using the format_results() method')
#         return pandas.read_csv(path, sep=self.sep).sort_values(by='RSS').reset_index(drop=True)
#
#     def read_PE_data_folder(self):
#         """
#
#         """
#         ## check that the data has been formatted before entry into PEAnalysis module
#         df_list = []
#         for i in glob.glob(os.path.join(self.results_path,'*.txt')):
#             df_list.append(self.read_PE_data_file(i))
#
#         return pandas.concat(df_list).sort_values(by='RSS').reset_index(drop=True)
#
#



@mixin(_base.UpdatePropertiesMixin)
@mixin(SaveFigMixin)
@mixin(ParseMixin)
@mixin(CreateResultsDirectoryMixin)
@mixin(TruncateDataMixin)
class Boxplot(PlotKwargs):
    """
    Create new folder for each experiment
    defined under the sub directory of results_directory
    """
    def __init__(self, cls, **kwargs):
        self.cls = cls
        self.kwargs = kwargs
        self.plot_kwargs = self.plot_kwargs()


        self.default_properties = {'sep': '\t',
                                   'log10': False,
                                   'truncate_mode': 'percent',
                                   'theta': 100,
                                   'num_per_plot': 6,
                                   'xtick_rotation': 'vertical',
                                   'ylabel': 'Estimated Parameter\n Value(Log10)',
                                   'title': 'Parameter Distributions',
                                   'savefig': False,
                                   'results_directory': None,
                                   'dpi': 300,
                                   'show': False}
        self.default_properties.update(self.plot_kwargs)
        for i in kwargs.keys():
            assert i in self.default_properties.keys(),'{} is not a keyword argument for Boxplot'.format(i)
        self.kwargs = self.default_properties
        self.default_properties.update(kwargs)
        self.default_properties.update(self.plot_kwargs)
        self.update_properties(self.default_properties)
        self._do_checks()

        self.data = self.parse(self.cls, log10=self.log10)
        self.data = self.truncate(self.data, mode=self.truncate_mode, theta=self.theta)
        self.plot()


    def _do_checks(self):
        pass

    def create_directory(self):
        """

        :return:
        """
        if self.results_directory is None:
            self.results_directory = os.path.join(self.cls.model.root, 'Boxplots')
            if os.path.isdir(self.results_directory) != True:
                os.makedirs(self.results_directory)
        return self.results_directory

    def plot(self):
        """
        Plot multiple parameter estimation data as boxplot
        :return:
        """

        labels = self.divide_data()
        for label_set in range(1, len(labels)):
            plt.figure()#
            data = self.data[labels[label_set]]
            seaborn.boxplot(data=data )
            plt.xticks(rotation=self.xtick_rotation)
            plt.title(self.title+'(n={})'.format(data.shape[0]))
            plt.ylabel(self.ylabel)
            if self.savefig:
                self.results_directory = self.create_directory()
                fle = os.path.join(self.results_directory,
                                   'Boxplot{}.jpeg'.format(label_set))
                plt.savefig(fle, dpi=self.dpi, bbox_inches='tight')

    def divide_data(self):
        """
        split data into multi plot
        :return:
        """
        n_vars = len(self.data.keys())
        n_per_plot = self.num_per_plot
#        assert n_per_plot<n_vars,'number of variables per plot must be smaller than the number of variables'
        int_division = n_vars//n_per_plot
        remainder = n_vars-(n_per_plot*int_division)
        l = []
        for i in range(int_division):
            l.append(self.data.keys()[i*n_per_plot:(i+1)*n_per_plot])
        l.append(self.data.keys()[-remainder:])
        return [list(i) for i in l]


@mixin(_base.UpdatePropertiesMixin)
@mixin(ParseMixin)
@mixin(TruncateDataMixin)
class RssVsIterations(PlotKwargs):
    """
    Create new folder for each experiment
    defined under the sub directory of results_directory
    """

    def __init__(self, cls, **kwargs):
        self.cls = cls
        self.kwargs = kwargs
        self.plot_kwargs = self.plot_kwargs()


        self.default_properties = {'sep': '\t',
                                   'log10': False,
                                   'truncate_mode': 'percent',
                                   'theta': 100,
                                   'num_per_plot': 6,
                                   'xtick_rotation': 'vertical',
                                   'ylabel': 'Estimated Parameter\n Value(Log10)',
                                   'title': 'Parameter Distributions',
                                   'savefig': False,
                                   'results_directory': None,
                                   'dpi': 300,
                                   'show': False}

        self.default_properties.update(self.plot_kwargs)
        for i in kwargs.keys():
            assert i in self.default_properties.keys(), '{} is not a keyword argument for Boxplot'.format(i)
        self.kwargs = self.default_properties
        self.default_properties.update(kwargs)
        self.default_properties.update(self.plot_kwargs)
        self.update_properties(self.default_properties)
        self._do_checks()

        self.data = self.parse(self.cls, log10=self.log10)
        self.plot()

    def _do_checks(self):
        """

        :return:
        """
        pass


    def create_directory(self):
        """
        create a directory for the results
        :return:
        """
        if self.results_directory is None:
            self.results_directory = os.path.join(self.cls.model.root,
                                                  'RssVsIterations')
        if not os.path.isdir(self.results_directory):
            os.makedirs(self.results_directory)
        return self.results_directory

    def plot(self):
        """
        
        """
            
        plt.figure()
        plt.plot(range(self.data['RSS'].shape[0]), self.data['RSS'].sort_values(ascending=True))
        plt.xticks(rotation=self.xtick_rotation)
        plt.title(self.title)
        plt.ylabel(self.ylabel)
        plt.xlabel('Rank of Best Fit')
        if self.savefig:
            self.results_directory = self.create_directory()
            fle = os.path.join(self.results_directory, 'RssVsIterations.jpeg')
            plt.savefig(fle, dpi=self.dpi, bbox_inches='tight')


@mixin(_base.UpdatePropertiesMixin)
@mixin(ParseMixin)
@mixin(TruncateDataMixin)
@mixin(CreateResultsDirectoryMixin)
class Pca(PlotKwargs):
    """
    Create new folder for each experiment
    defined under the sub directory of results_directory
    """

    def __init__(self, cls, **kwargs):
        self.cls = cls
        self.kwargs = kwargs
        self.plot_kwargs = self.plot_kwargs()

        self.default_properties={'sep': '\t',
                                 'truncate_mode': 'percent',
                                 'theta': 100,
                                 'log10': False,
                                 'ylabel': None,
                                 'xlabel': None,
                                 'title': None,
                                 'savefig': False,
                                 'results_directory': None,
                                 'dpi': 300,
                                 'n_components': 2,
                                 'by': 'parameters', ##iterations or parameters
                                 'legend_position': None, ##Horizontal, verticle, line spacing
                                 'legend_fontsize': 25,
                                 'cmap': 'viridis',
                                 'annotate': False,
                                 'annotation_fontsize': 25,
                                 'show': False,
                                 }


        self.default_properties.update(self.plot_kwargs)
        for i in kwargs.keys():
            assert i in self.default_properties.keys(), '{} is not a keyword argument for Pca'.format(i)
        self.kwargs = self.default_properties
        self.default_properties.update(kwargs)
        self.default_properties.update(self.plot_kwargs)
        self.update_properties(self.default_properties)
        self._do_checks()

        self.data = self.parse(self.cls, log10=self.log10)
        self.data = self.truncate(self.data, mode=self.truncate_mode, theta=self.theta)
        self.pca()


    def _do_checks(self):
        """
        varify integrity of user input
        :return:
        """


        if self.by not in ['parameters','iterations']:
            raise errors.InputError('{} not in {}'.format(
                self.by, ['parameters','iterations']))

        if self.results_directory is None:
            self.results_directory = os.path.join(self.cls.model.root, 'PCA')

        if self.ylabel==None:
            if self.log10==False:
                self.ylabel = 'PC2'
            elif self.log10==True:
                self.ylabel = 'PC2(Log10)'
            else:
                raise errors.SomethingWentHorriblyWrongError('{} not in {}'.format(
                    self.ylabel, [True, False]))
        
        if self.xlabel==None:
            if self.log10==False:
                self.xlabel = 'PC1'
            elif self.log10==True:
                self.xlabel = 'PC1(Log10)'
            else:
                raise errors.SomethingWentHorriblyWrongError(
                    '{} not in {}'.format(self.ylabel, [True, False]))
 
        
        LOG.info('plotting PCA {}'.format(self.by))
        
        if self.by == 'parameters':
            self.annotate=True
            if self.legend_position==None:
                LOG.critical(
                    'When data reduction is by \'parameters\' you should specify an argument to legend_position. i.e. legend_position=(10,10,1.5) for horizontal, vertical and linespacing')


        if self.legend_position is None:
            self.legend_position = (1, 1, 0.5) ##horizontal, verticle, linespacing

    def pca(self):
        pca = PCA(n_components=self.n_components)
        rss = self.data.RSS
        self.data = self.data.drop('RSS',axis=1)
        fig, ax = plt.subplots()
        if self.by == 'parameters':
            projected = pca.fit(self.data.transpose()).transform(self.data.transpose())
            projected = pandas.DataFrame(projected, index=self.data.columns)
            labels = self.data.columns
            title = 'PCA by Parameters (n={})'.format(len(labels))
            sc = ax.scatter(projected[0], projected[1])


        else:
            projected = pca.fit(self.data).transform(self.data)
            projected = pandas.DataFrame(projected, index=self.data.index)
            labels = list(self.data.index)
            title = 'PCA by Iterations (n={})'.format(len(labels))
            projected = pandas.concat([rss, projected], axis=1)
            sc = ax.scatter(projected[0], projected[1], c=projected['RSS'], cmap=self.cmap)
            cb = plt.colorbar(sc)
            cb.ax.set_title('RSS')
            
            
        plt.ylabel(self.ylabel)
        plt.xlabel(self.xlabel)
        plt.title(title)
        #TODO connect copasi with the python community
        #TODO mjor selling point for pycoools.
        #TODO interafce with pysces, pyDStools and sloppycell
        for i, txt in enumerate(labels):
            if self.annotate:
                ax.annotate(str(i), (projected[0][i], projected[1][i]),
                            fontsize=self.annotation_fontsize)
            if self.by == 'parameters':
                ax.text(self.legend_position[0],
                        self.legend_position[1]-i*self.legend_position[2],
                    '{}: {}'.format(i,txt),fontsize=self.legend_fontsize)
        if self.savefig:
            self.create_directory(self.results_directory)
            fle = os.path.join(self.results_directory, 'Pca_by_{}'.format(self.by))
            plt.savefig(fle, dpi=self.dpi, bbox_inches='tight')

@mixin(_base.UpdatePropertiesMixin)
@mixin(ParseMixin)
@mixin(TruncateDataMixin)
@mixin(CreateResultsDirectoryMixin)
class Histograms(PlotKwargs):
    """
    Create new folder for each experiment
    defined under the sub directory of results_directory
    """

    def __init__(self, cls, **kwargs):
        self.cls = cls
        self.kwargs = kwargs
        self.plot_kwargs = self.plot_kwargs()

        self.default_properties = {'sep': '\t',
                                   'log10': False,
                                   'truncate_mode': 'percent',
                                   'theta': 100,
                                   'xtick_rotation': 'horizontal',
                                   'ylabel': 'Frequency',
                                   'savefig': False,
                                   'results_directory': None,
                                   'dpi': 300,
                                   'title_fontsize': 35,
                                   'show': False}

        self.default_properties.update(self.plot_kwargs)
        for i in kwargs.keys():
            assert i in self.default_properties.keys(), '{} is not a keyword argument for Histograms'.format(i)
        self.kwargs = self.default_properties
        self.default_properties.update(kwargs)
        self.default_properties.update(self.plot_kwargs)
        self.update_properties(self.default_properties)
        self._do_checks()

        self.data = self.parse(self.cls, log10=self.log10)
        self.data = self.truncate(self.data, mode=self.truncate_mode, theta=self.theta)
        LOG.info('plotting histograms')
        self.plot()

    def _do_checks(self):
        """

        :return:
        """
        if self.results_directory is None:
            self.results_directory = os.path.join(self.cls.model.root, 'Histograms')


    def plot(self):
        """
        
        """
        for parameter in self.data.keys():
            plt.figure()
            seaborn.distplot(self.data[parameter])
            plt.ylabel(self.ylabel)
            plt.title('{},n={}'.format(parameter, self.data[parameter].shape[0]),
                      fontsize=self.title_fontsize)
            if self.savefig:
                self.create_directory(self.results_directory)
                fname = os.path.join(self.results_directory,
                                     misc.RemoveNonAscii(parameter).filter+'.jpeg')
                plt.savefig(fname, dpi=self.dpi, bbox_inches='tight')


@mixin(_base.UpdatePropertiesMixin)
@mixin(ParseMixin)
@mixin(TruncateDataMixin)
@mixin(CreateResultsDirectoryMixin)
class Scatters(PlotKwargs):
    """
    Create new folder for each experiment
    defined under the sub directory of results_directory
    """

    def __init__(self, cls, **kwargs):
        self.cls = cls
        self.kwargs = kwargs
        self.plot_kwargs = self.plot_kwargs()

        self.default_properties = {
            'x':'RSS',
            'y': None,
            'sep': '\t',
            'log10': False,
            'cmap': 'jet_r',
            'truncate_mode': 'percent',
            'theta': 100,
            'xtick_rotation': 'horizontal',
            'ylabel': 'Frequency',
            'savefig': False,
            'results_directory': None,
            'dpi': 300,
            'title_fontsize': 35,
            'show': False}

        self.default_properties.update(self.plot_kwargs)
        for i in kwargs.keys():
            assert i in self.default_properties.keys(), '{} is not a keyword argument for Scatters'.format(i)
        self.kwargs = self.default_properties
        self.default_properties.update(kwargs)
        self.default_properties.update(self.plot_kwargs)
        self.update_properties(self.default_properties)
        self._do_checks()

        self.data = self.parse(self.cls, log10=self.log10)
        self.data = self.truncate(self.data, mode=self.truncate_mode, theta=self.theta)
        self.plot()

    def _do_checks(self):
        """

        :return:
        """
        if isinstance(self.x, str):
            self.x = [self.x]

        if self.results_directory is None:
            self.results_directory = os.path.join(self.cls.model.root, 'Scatters')

    def plot(self):
        """

        :return:
        """
        if self.y is None:
            self.y = self.data.keys()

        for x_var in self.x:
            for y_var in self.y:
                plt.figure()
                plt.scatter(
                    self.data[x_var], self.data[y_var],
                    cmap=self.cmap, c=self.data['RSS'],
                )
                cb = plt.colorbar()
                cb.set_label('RSS')
                plt.xlabel(x_var)
                plt.ylabel(y_var)
                plt.title('Scatter graph of\n {} Vs {}'.format(x_var, y_var))
                if self.savefig:
                    x_dir = os.path.join(self.results_directory, x_var)
                    self.create_directory(x_dir)
                    fle = os.path.join(x_dir, '{}.jpeg'.format(y_var))
                    plt.savefig(fle, dpi=self.dpi, bbox_inches='tight')

        if self.show:
            plt.show()

@mixin(_base.UpdatePropertiesMixin)
@mixin(ParseMixin)
@mixin(TruncateDataMixin)
@mixin(CreateResultsDirectoryMixin)
class LinearRegression(PlotKwargs):
    """
    Create new folder for each experiment
    defined under the sub directory of results_directory
    """

    def __init__(self, cls, **kwargs):
        self.cls = cls
        self.kwargs = kwargs
        self.plot_kwargs = self.plot_kwargs()

        self.default_properties = {
            'lin_model': linear_model.LassoCV,
            'log10': False,
            'truncate_mode': 'percent',
            'theta': 100,
            'xtick_rotation': 'horizontal',
            'ylabel': 'Frequency',
            'savefig': False,
            'results_directory': None,
            'dpi': 300,
            'title_fontsize': 35,
            'show': False,
            'n_alphas': 100,
            'max_iter': 20000
        }

        self.default_properties.update(self.plot_kwargs)
        for i in kwargs.keys():
            assert i in self.default_properties.keys(), '{} is not a keyword argument for LinearRegression'.format(i)
        self.kwargs = self.default_properties
        self.default_properties.update(kwargs)
        self.default_properties.update(self.plot_kwargs)
        self.update_properties(self.default_properties)
        self._do_checks()

        self.data = self.parse(self.cls, log10=self.log10)
        self.data = self.truncate(self.data, mode=self.truncate_mode, theta=self.theta)
        


        self.scores, self.coef = self.compute_coefficients()
        self.coef = self.coef.fillna(value=0)
        
        self.plot_rss()
        self.plot_scores()
        self.plot_coef()

    def _do_checks(self):
        """

        :return:
        """
        if self.results_directory is None:
            self.results_directory = os.path.join(self.cls.model.root, 'LinearRegression')


    def compute1coef(self, parameter):
        """
        Compute coefficients for a single parameter
        using self['lin_model'] from sklearn
        """
#        print self.data[y]
        y = numpy.array(self.data[parameter])
        X = self.data.drop(parameter, axis=1)
        X_train, X_test, y_train, y_test = model_selection.train_test_split(X, y)
        
        lin_model = self.lin_model(fit_intercept=True, n_alphas=self.n_alphas,
                    max_iter=self.max_iter)
        
        lin_model.fit(X_train,y_train)
        df = pandas.DataFrame(lin_model.coef_, index=X.columns, columns=[parameter])#.sort_values(by='Coefficients')
        df['abs_values'] = numpy.absolute(df[parameter])
        df = df.sort_values(by='abs_values', ascending=False)
        df = df.drop('abs_values', axis=1)
        scores = [lin_model.score(X_train, y_train), lin_model.score(X_test, y_test)]
        scores = pandas.DataFrame(scores, index=['TrainScore', 'TestScore'])
        return scores, df
    
    def compute_coefficients(self):
        parameters = list(self.data.columns)
        df_dct = {}
        score_dct={}
        for y in parameters:
            score_dct[y], df_dct[y] = self.compute1coef(y)
            
        df1 = pandas.concat(score_dct,axis=1).transpose().sort_values(by='TestScore',
                           ascending=False)
        df2 = pandas.concat(df_dct,axis=1)
        return df1, df2
    
    def plot_scores(self):
        """
        
        """
        plt.figure()
        seaborn.heatmap(self.scores)
        plt.title('Model Fitting Test and Train Scores'+'(n={})'.format(self.data.shape[0]),
                  fontsize=self.title_fontsize)
        if self.savefig:
            save_dir = os.path.join(self.results_directory, 'LinearRegression')
            self.create_directory(self.results_directory)
            fname = os.path.join(self.results_directory, 'linregress_scores.jpeg')
            plt.savefig(fname, dpi=self.dpi, bbox_inches='tight')
        
        
    def plot_rss(self):
        plt.figure()
        seaborn.heatmap(self.coef.RSS.sort_values(by='RSS', ascending=False))
        plt.title('Lasso Regression. Y=RSS, X=all other Parameters'+'(n={})'.format(self.data.shape[0]), fontsize=self.title_fontsize)
        if self.savefig:
            self.create_directory(self.results_directory)
            fname = os.path.join(self.results_directory, 'linregress_RSS.jpeg')
            plt.savefig(fname, dpi=self.dpi, bbox_inches='tight')
                
        
    def plot_coef(self):
        """

        :return:
        """
        self.coef = self.coef.drop('RSS', axis=1)
        self.coef = self.coef.drop('RSS', axis=0)
#        print self.coef
        plt.figure()
        seaborn.heatmap(self.coef)
        plt.title('Coefficient Heatmap. Parameters Vs Parameters',fontsize=self.title_fontsize)
        plt.xlabel('')
        if self.savefig:
            self.create_directory(self.results_directory)
            fname = os.path.join(self.results_directory, 'linregress_parameters.jpeg')
            plt.savefig(fname, dpi=self.dpi, bbox_inches='tight')


@mixin(_base.UpdatePropertiesMixin)
@mixin(ParseMixin)
@mixin(TruncateDataMixin)
@mixin(CreateResultsDirectoryMixin)
class EnsembleTimeCourse(object):
    """
    
    
    To Do:
        - Build option for including experimental data on the plots 
    """
    
    def __init__(self, cls, **kwargs):
        self.cls = cls
        options = {'sep': '\t',
                   'y' : None,
                   'x': 'time',
                   'truncate_mode': 'percent',
                   'theta': 5,
                   'xtick_rotation': 'horizontal',
                   'ylabel': 'Frequency',
                   'savefig': False,
                   'results_directory': None,
                   'dpi': 300,
                   'step_size': 1,
                   'check_as_you_plot': False,
                   'estimator': numpy.mean,
                   'n_boot': 10000,
                   'ci': 95,
                   'color': 'deep',
                   'show': False} ##resolution: intervals in time course
        
        for i in kwargs.keys():
            assert i in options.keys(),'{} is not a keyword argument for ParameterEnsemble'.format(i)
        options.update( kwargs)  
        self.kwargs = options
        self.update_properties(self.kwargs)
        self._do_checks()

        self.data = self.parse(self.cls, log10=False)
        self.data = self.truncate(self.data,
                                  mode=self.truncate_mode,
                                  theta=self.theta)



        self.experimental_data = self.parse_experimental_files()
        self.exp_times = self.get_experiment_times()
        self.ensemble_data = self.simulate_ensemble()
        self.ensemble_data.index = self.ensemble_data.index.rename(['Index','Time'])
        self.plot()

    def _do_checks(self):
        
        if self.results_directory == None:
            self.results_directory = os.path.join(self.cls.model.root, 'EnsembleTimeCourses' )
            
    def parse_experimental_files(self):
        df_dct={}
        for i in range(len(self.cls.experiment_files)):
            df=pandas.read_csv(self.cls.experiment_files[i],
                               sep='\t')
            df_dct[self.cls.experiment_files[i]] = df
        return df_dct

    def get_experiment_times(self):
        d={}
        for i in self.experimental_data:
            d[i]={}
            for j in self.experimental_data[i].keys():
                if j.lower() == 'time':
                    d[i]= self.experimental_data[i][j]
                    
        times={}
        for i in d:
            times[i]={}
            times[i]['start'] = d[i].iloc[0]
            times[i]['end'] = d[i].iloc[-1]
            times[i]['step_size'] = d[i].iloc[1]-d[i].iloc[0]
            '''
            subtract 1 from intervals to account for header
            '''
            times[i]['intervals']=int(d[i].shape[0])-1
        return times
        
    def simulate_ensemble(self):
        """
        
        """


        ## collect end times for each experiment
        ##in order to find the biggest
        end_times = []
        for i in self.exp_times:
            ## start creating a results dict while were at it
            end_times.append(self.exp_times[i]['end'])
        intervals =  max(end_times)/self.step_size
        
        d={}
        for i in range(self.data.shape[0]):
            LOG.info('inserting parameter set {}'.format(i))
            I=model.InsertParameters(self.cls.model, df=self.data, index=i)
            LOG.info(I.parameters.transpose().sort_index())
            TC = tasks.TimeCourse(self.cls.model.copasi_file,
                                  end=max(end_times),
                                  step_size=self.step_size,
                                  intervals=intervals,
                                  plot=False)
            if self.check_as_you_plot:
                self.cls.model.open()
            d[i] = self.parse(TC, log10=False)
        return pandas.concat(d)

    def plot(self):
        """
        
        """
        if self.y == None:
            LOG.debug('ensemble data keys --> {}'.format(self.ensemble_data.keys()))
            self.y = list(self.ensemble_data.keys())

        if isinstance(self.y, list) != True:
            self.y = [self.y]

        for param in self.y:
            if param not in self.ensemble_data.keys():
                raise errors.InputError('{} not in your data set. {}'.format(param, self.ensemble_data.keys()))

        data = self.ensemble_data.reset_index(level=1, drop=True)
        data.index.name = 'ParameterFitIndex'
        data = data.reset_index()
        for parameter in self.y:
            if parameter not in ['ParameterFitIndex','Time']:
                plt.figure()
                ax = seaborn.tsplot(data, time='Time', value=parameter,
                                 unit='ParameterFitIndex',
                                 estimator=self.estimator,
                                 n_boot=self.n_boot,
                                 ci=self.ci,
                                 color=self.color)
                LOG.debug('experiemntal data --> {}'.format(self.experimental_data))
                LOG.debug('parameter --> {}'.format(parameter))
                plt.plot(self.experimental_data[self.experimental_data.keys()[0]]['Time'],
                                              self.experimental_data[self.experimental_data.keys()[0]][parameter],
                                              'ro', label='Exp')
                plt.title('Ensemble Time Course\n for {} (n={})'.format(parameter, self.data.shape[0]))
                if self.savefig:
                    self.create_directory(self.results_directory)
                    fname = os.path.join(self.results_directory, '{}.jpeg'.format(misc.RemoveNonAscii(parameter).filter))
                    plt.savefig(fname, dpi=self.dpi, bbox_inches='tight')
        

# @mixin(DefaultResultsDirectoryMixin)

@mixin(TruncateDataMixin)
@mixin(_base.UpdatePropertiesMixin)
class ModelSelection(object):
    '''
    ## could give
    '''
    def __init__(self,multi_model_fit, **kwargs):
        self.multi_model_fit=multi_model_fit
        self.number_models=self.get_num_models()
        
        options={#report variables
                 'savefig':False,
                 'results_directory':self.multi_model_fit.project_dir,
                 'dpi':300}
                 
        for i in kwargs.keys():
            assert i in options.keys(),'{} is not a keyword argument for ModelSelection'.format(i)
        options.update( kwargs) 
        self.kwargs=options
        self.update_properties(self.kwargs)
        raise NotImplementedError
        
        
#        if self.model_selection_filename==None:
#            self.model_selection_filename=os.path.join(self.multi_model_fit.wd,'ModelSelectionData.xlsx')
        self.results_folder_dct=self._get_results_directories()
        self._PED_dct=self._parse_data()
        self.GMQ_dct=self._get_GMQ_dct()
        self.number_model_parameters=self._get_number_estimated_model_parameters()
        self.number_observations=self._get_n()
        self.model_selection_data=self.calculate_model_selection_criteria()
        

    def __getitem__(self,key):
        if key not in self.kwargs.keys():
            raise TypeError('{} not in {}'.format(key,self.kwargs.keys()))
        return self.kwargs[key]

    def __setitem__(self,key,value):
        self.kwargs[key] = value
        
    def get_num_models(self):
        return len(self.multi_model_fit.cps_files)
    ## void
    def to_excel(self,filename):
        self.model_selection_data.to_excel(filename)
        
    def _get_results_directories(self):
        '''
        Find the results directories embedded within MultimodelFit
        and RunMutliplePEs. 
        '''
        LOG.debug('Finding location of parameter estimation results:')
        dct=self.multi_model_fit.results_folder_dct
        for key in dct:
            LOG.debug('Key to results folder dict is the cps file: \n{}'.format(key))
            LOG.debug('Value to results folder dict is the output results folder: \n{}'.format(dct[key]))
            LOG.debug('Checking that the results folder exists: ... {}'.format(os.path.isdir(dct[key])))
        return dct
    
    def _parse_data(self):
        '''
        
        '''
        
        PED_dct={}
        LOG.debug('Here is the results folder:\n{}'.format(self.results_folder_dct))
        LOG.debug('The results folder vairable is of type {}'.format(type(self.results_folder_dct)))
#        for i in self._results_folders:
#            print i,self._results_folder[i]
#        print type(self._results_folders)
#        print len(self._results_folders.items())
        for folder in self.results_folder_dct:
            LOG.debug('parsing data from folder')
            LOG.debug('checking results folder exists: {}'.format(os.path.isdir(self.results_folder_dct[folder]),self.results_folder_dct[folder]))
            PED_dct[folder]=ParsePEData(self.results_folder_dct[folder])
            
        LOG.info('data successfully parsed from {} models into Python'.format(len(self.results_folder_dct.items())))
        return PED_dct
            
    def _get_GMQ_dct(self):
        '''
        iterate over each model and get the corresponding
        GetModelQuantities class for each. 
        '''
        LOG.debug('Instantiating GetModelQuantities per model')
        GMQ_dct={}
        for model in self.multi_model_fit.sub_cps_dirs:
            LOG.debug('Key:\t{}'.format(model))
            LOG.debug('Value \t{}'.format(self.multi_model_fit.sub_cps_dirs[model]))
            GMQ_dct[self.multi_model_fit.sub_cps_dirs[model]]=tasks.GetModelQuantities(self.multi_model_fit.sub_cps_dirs[model])
        LOG.debug('GetModelQuantities Instantiated')
        return GMQ_dct
    
    def _get_number_estimated_model_parameters(self):
        '''
        
        '''
        k_dct={}
        for GMQ in self.GMQ_dct:
            LOG.debug( 'model at {} has {} estimated parameters'.format(GMQ,len(self.GMQ_dct[GMQ].get_fit_items().items())))
            k_dct[GMQ]=len(self.GMQ_dct[GMQ].get_fit_items().items())
        return k_dct
            
    def _get_n(self):
        '''
        get number of observed data points for AIC calculation
        '''
        LOG.info('Counting number of observed data points:...')
        LOG.debug('Number of Experiment Files: \t{}'.format(len(self.multi_model_fit.exp_files)))
        n={}
        for exp in self.multi_model_fit.exp_files:
            data=pandas.read_csv(exp,sep='\t')
            l=[]
            for key in data.keys() :
                if key.lower()!='time':
                    if key[-6:]!='_indep':
                        LOG.debug('Dimensions of data at file \n{} is \n{}'.format(exp,data[key].shape))
                        l.append(int(data[key].shape[0]))
            n[exp]=sum(l)
        n=sum(n.values())
        LOG.debug('Final sum of all data files is {}'.format(n))
        return n
        
        
    
    def calculate1AIC(self,RSS,K,n):
        '''
        Calculate the corrected AIC:
            
            AICc = -2*ln(RSS/n) + 2*K + (2*K*(K+1))/(n-K-1) 
                
            or if likelihood function used instead of RSS
                                
            AICc = -2*ln(likelihood) + 2*K + (2*K*(K+1))/(n-K-1)
            
        Where:
            RSS:
                Residual sum of squares for model fit
            n:
                Number of observations collectively in all data files
                
            K:
                Number of model parameters
        '''
        return n*numpy.log((RSS/n))  + 2*K + (2*K*(K+1))/(n-K-1) 
        
    
    def calculate1BIC(self,RSS,K,n):
        '''
        Calculate the bayesian information criteria
            BIC = -2*ln(likelihood) + k*ln(n)
            
                Does this then go to:
                    
            BIC = -2*ln(RSS/n) + k*ln(n)
        '''
        return  (n*numpy.log(RSS/n) ) + K*numpy.log(n)
    
    def calculate_model_selection_criteria(self):
        '''
        
        '''
        LOG.debug('calculating model selection criteria AIC and BIC')
        LOG.debug('self.multi_model_fit.sub_cps_dirs is of type {}'.format(type(self.multi_model_fit.sub_cps_dirs)))
        df_dct={}
        for model_num in range(len(self.multi_model_fit.sub_cps_dirs)):
            keys=self.multi_model_fit.sub_cps_dirs.keys()
            LOG.debug( 'Calculating MSC for model \t{}'.format(keys[model_num]))
            cps_key=self.multi_model_fit.sub_cps_dirs[keys[model_num]]
            k=self.number_model_parameters[cps_key]
            LOG.debug('k is {}'.format(k))
            n=self.number_observations #constant throughout analysis 
            LOG.debug('n is {}'.format(n))
            RSS=self._PED_dct[cps_key].data.RSS
            LOG.debug(RSS.shape)
            aic_dct={}
            bic_dct={}
            LOG.debug('Full RSS Series')
            LOG.debug(RSS)
            for i in range(len(RSS)):
                LOG.debug('In RSS vector: {},{}'.format(i,RSS.iloc[i]))
                aic=self.calculate1AIC(RSS.iloc[i],k,n)
                bic=self.calculate1BIC(RSS.iloc[i],k,n)
                aic_dct[i]=aic
                bic_dct[i]=bic
                LOG.debug('In idx,RSS,AIC,BIC: {},{},{},{}'.format(i,RSS.iloc[i],aic,bic))
            LOG.debug('RSS for model:\n{}'.format(RSS.to_dict()))
            LOG.debug('AICc calculation produced:\n{}'.format(aic_dct))
            LOG.debug('BIC calculation produced:\n{}'.format(bic_dct))
            LOG.debug('{},{}'.format(i,RSS[i]))
            aic= pandas.DataFrame.from_dict(aic_dct,orient='index')
            RSS= pandas.DataFrame(RSS)
            bic= pandas.DataFrame.from_dict(bic_dct,orient='index')
            LOG.debug(aic)
            LOG.debug(RSS)
            LOG.debug(bic)
            df=pandas.concat([RSS,aic,bic],axis=1)
            df.columns=['RSS','AICc','BIC']
            df.index.name='RSS Rank'
            df_dct[os.path.split(cps_key)[1]]=df
            LOG.debug('\n{}'.format(df))
        df=pandas.concat(df_dct,axis=1)
        LOG.debug(df)
        return df
    
    
    def plot_boxplot(self):
        '''
        
        '''
        data = self.model_selection_data
        
        data = data.unstack()
        data = data.reset_index()
        data = data.rename(columns={'level_0':'Model',
                                    'level_1':'Metric',
                                    0:'Score'})
#        print data
        for metric in data['Metric'].unique():
            plt.figure()
            seaborn.boxplot(data = data[data['Metric']==metric],
                            x='Model',y='Score')
            plt.xticks(rotation='vertical')
            plt.title('{} Scores'.format(metric))
            plt.xlabel(' ')
            if self.savefig:
                save_dir = os.path.join(self.results_directory, 'ModelSelectionGraphs')
                if os.path.isdir(save_dir)!=True:
                    os.mkdir(save_dir)
                os.chdir(save_dir)
                fname = os.path.join(save_dir, '{}.png'.format(metric))
                plt.savefig(fname, dpi=self['dpi'], bbox_inches='tight')
  
        
        
        
    def chi2_lookup_table(self,alpha):
        '''
        Looks at the cdf of a chi2 distribution at incriments of 
        0.1 between 0 and 100. 
        
        Returns the x axis value at which the alpha interval has been crossed, 
        i.e. gets the cut off point for chi2 dist with DOF and alpha . 
        '''
        nums= numpy.arange(0,100,0.1)
        table=zip(nums,scipy.stats.chi2.cdf(nums,self.kwargs.get('DOF')) )
        for i in table:
            if i[1]<=alpha:
                chi2_df_alpha=i[0]
        return chi2_df_alpha  
        
    def get_chi2_alpha(self):
        '''
        return the chi2 threshold for cut off point alpha and DOF degrees of freedom
        '''
        dct={}
        alphas=numpy.arange(0,1,0.01)
        for i in alphas:
            dct[round(i,3)]=self.chi2_lookup_table(i)
        return dct[0.05]
    
    def call_fit_analysis_script(self,tolerance=0.001):
        '''
        
        '''
        LOG.debug('calling fit analysis script')
        for i in self.multi_model_fit.results_folder_dct:
            LOG.debug('\tKey :\n{}\nValue:\n{}'.format(i,self.multi_model_fit.results_folder_dct[i]))
            self.run_fit_analysis(self.multi_model_fit.results_folder_dct[i])

#    @ipyparallel.dview.remote(block=True)
    def run_fit_analysis(self,results_path,tolerance=0.001):
        '''
        
        '''
        scripts_folder=os.path.join(os.path.dirname(os.path.abspath(__file__)),'Scripts')
        fit_analysis_script_name=os.path.join(scripts_folder,'fit_analysis.py')
        LOG.debug('fit analysis script on your computer is at \t\t{}'.format(fit_analysis_script_name))

        return Popen(['python',fit_analysis_script_name,results_path,'-tol', tolerance])
#        
    def compare_sim_vs_exp(self):
        '''
        
        '''
        LOG.info('Visually comparing simulated Versus Experiemntal data.')
        
        for cps, res in self.multi_model_fit.results_folder_dct.items():
            LOG.debug('running current solution statistics PE with:\t {}'.format(cps))
            tasks.InsertParameters(cps,parameter_path=res, index=0)
            PE=tasks.ParameterEstimation(cps,self.multi_model_fit.exp_files,
                                       randomize_start_values=False,
                                       method='CurrentSolutionStatistics',
                                       plot=True,savefig=True,
                                       )
            PE.set_up()
            PE.run()
            PE.format_results()
            
            
    def get_best_parameters(self,filename=None):
        '''
        
        '''
        df=pandas.DataFrame()
        for cps, res in self.multi_model_fit.results_folder_dct.items():
            df[os.path.split(cps)[1]]= ParsePEData(res).data.iloc[0]
            
        if filename==None:
            return df
        else:
            df.to_excel(filename)
            return df
        
        
        
    def compare_model_parameters(self,parameter_list,filename=None):
        '''
        Compare all the parameters accross multiple models 
        in a bar chart averaging and STD for a parameter accross
        all models. 
        
        May have a problem with different models have different 
        parameters as they are not directly comparible
        '''
        best_parameters=self.get_best_parameters()
        data= best_parameters.loc[parameter_list].transpose()
        f=seaborn.barplot(data=numpy.log10(data))
        f.set_xticklabels(parameter_list,rotation=90)
        plt.legend(loc=(1,1))
        plt.title('Barplot Comparing Parameter Estimation Results for specific\nParameters accross all models')
        plt.ylabel('log10(parameter_value),Err=SEM')
        if filename!=None:
            plt.savefig(filename,dpi=200,bbox_inches='tight')
#
        
        
if __name__=='__main__':
    pass
#    execfile('/home/b3053674/Documents/pycotools/pycotools/pycotoolsTutorial/Test/testing_kholodenko_manually.py')

    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    



















