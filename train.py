import numpy as np
import os
from tqdm import tqdm
import pandas as pd
import tensorflow as tf

import preprocessing
from preprocessing import get_behavioral_test, preprocess_behavioral_dict
import models
from models import VGG3DModel, VGGSlicedModel, VGGACSModel, EEGModel



def print_results(models, test_data, test_labels, metrics):
    """
    prints the results of each model after training
    """

    table = []
    
    for model in models:
        table.append([])
        for metric in metrics:
            table[-1].append(metric(test_labels, model.call(test_data)).numpy())
    
    table_df = pd.DataFrame(
        data=table, 
        index=[model.name for model in models], 
        columns=[str(type(metric)).split('\'')[1].split('.')[-1] for metric in metrics])
    print()
    print(table_df)
    print()


def get_patientIDs(filepath, mri_dir, eeg_dir, sync=True):
    """
    retrieve shared list of patientIDs
    filepath        : path to data directory
    eeg_dir         : eeg dir name
    mri_dir         : mri dir name
    """

    mri_patientIDs = set(os.listdir(filepath + mri_dir))
    eeg_patientIDs = set(os.listdir(filepath + eeg_dir))
    if ".DS_Store" in mri_patientIDs: mri_patientIDs.remove(".DS_Store")
    if ".DS_Store" in eeg_patientIDs: eeg_patientIDs.remove(".DS_Store")
    if sync: patientIDs = list(mri_patientIDs.intersection(eeg_patientIDs))
    else: patientIDs = list(mri_patientIDs.union(eeg_patientIDs))
    patientIDs = [patientID.replace(".npy", "") for patientID in patientIDs]
    patientIDs.sort()

    return patientIDs


def load_acs_mri_data(filepath, mri_dir, patientIDs):
    """
    load preprocessed acs mri data
    filepath        : path to data directory
    mri_dir         : mri dir name
    patientIDs      : patientID list
    """

    print("loading mri data from", filepath, "...")
    acs_mri_data = []
    for patientID in tqdm(patientIDs):
        patient_mri = np.load(filepath + mri_dir + patientID + ".npy")
        acs_mri_data.append(patient_mri)
    acs_mri_data = np.stack(acs_mri_data)

    return acs_mri_data


def load_eeg_data(filepath, eeg_dir, patientIDs):
    """
    load preprocessed eeg data
    filepath        : path to data directory
    eeg_dir         : eeg dir name
    patientIDs      : patientID list
    """

    print("loading eeg data from", filepath, "...")
    eeg_data = []
    for patientID in tqdm(patientIDs):
        patient_eeg = np.load(filepath + eeg_dir + patientID + ".npy")
        eeg_data.append(patient_eeg)
    eeg_data = np.stack(eeg_data)

    return eeg_data


def load_behavioral_data(filepath, behavioral_dir, patientIDs):
    """
    load preprocessed behavioral data
    filepath        : path to data directory
    behavioral_dir  : behavioral dir name
    patientIDs      : patientID list
    """

    behavioral_path = filepath + behavioral_dir
    behavioral_test = ['cvlt', 'lps']
    behavioral_test_data = [preprocess_behavioral_dict(get_behavioral_test(behavioral_path, test)) for test in behavioral_test]

    print("loading behavioral data from", filepath, "...")
    behavioral_data = []
    for patientID in tqdm(patientIDs):
        behavioral_data.append([])
        for test_data in behavioral_test_data:
            behavioral_data[-1] += test_data[patientID]
        behavioral_data[-1] = np.array(behavioral_data[-1])
    behavioral_data = np.stack(behavioral_data)

    return behavioral_data


def load_data(filepath, mri_dir, eeg_dir, behavioral_dir, patientIDs):
    """
    load preprocessed data
    filepath        : path to data directory
    eeg_dir         : eeg dir name
    mri_dir         : mri dir name
    behavioral_dir  : behavioral dir name
    return          : mri_data, eeg_data, behavioral_data
    """

    print()
    acs_mri_data = load_acs_mri_data(filepath, mri_dir, patientIDs)
    eeg_data = load_eeg_data(filepath, eeg_dir, patientIDs)
    behavioral_data = load_behavioral_data(filepath, behavioral_dir, patientIDs)
    print()

    return  acs_mri_data, eeg_data, behavioral_data


def main():

    mri_dir = "data/mri/"
    eeg_dir = "data/eeg/"
    behavioral_dir = "data/behavioral/"
    
    patientIDs = get_patientIDs("", mri_dir, eeg_dir, sync=True)

    mri_data, eeg_data, behavioral_data = load_data(
        "", 
        mri_dir, # preprocessing.MRI_RESULT_DIR, 
        eeg_dir, # preprocessing.EEG_RESULT_DIR,
        behavioral_dir, # preprocessing.BEHAVIORAL_DIR,
        patientIDs)

    train_patientIDs, test_patientIDs = preprocessing.train_test_split(patientIDs)
    train_mri_data, test_mri_data = preprocessing.train_test_split(mri_data)
    train_eeg_data, test_eeg_data = preprocessing.train_test_split(eeg_data)
    train_behavioral_data, test_behavioral_data = preprocessing.train_test_split(behavioral_data)


    eegnet_model = models.EEGModel(output_units=behavioral_data.shape[1])
    eegnet_model.compile(optimizer=eegnet_model.optimizer, loss=eegnet_model.loss, metrics=[])
    eegnet_model.build(train_eeg_data.shape)
    eegnet_model.summary()
    # eegnet_model.fit(train_eeg_data, train_behavioral_data, batch_size=4, epochs=10, validation_data=(test_eeg_data, test_behavioral_data))

    print("\ntraining control models ...\n")

    center_model = models.CenterModel(name="control (center)", shape=test_behavioral_data.shape)
    mean_model = models.MeanModel(name="control (mean)", train_labels=train_behavioral_data)
    median_model = models.MedianModel(name="control (median)", train_labels=train_behavioral_data)
    simple_nn = models.SimpleNN(name="control (1layerNN)", output_units=behavioral_data.shape[1])
    simple_nn.compile(optimizer=simple_nn.optimizer, loss=simple_nn.loss, metrics=[])
    simple_nn.fit(train_mri_data, train_behavioral_data, batch_size=4, epochs=1, validation_data=(test_mri_data, test_behavioral_data))

    print("\ntraining new models ...\n")

    vgg_acs_model = VGGACSModel(input_shape=train_mri_data.shape[1:], output_units=behavioral_data.shape[1])
    vgg_acs_model.compile(
		optimizer=vgg_acs_model.optimizer,
		loss=vgg_acs_model.loss,
		metrics=[],
	)
    vgg_acs_model.build(train_mri_data.shape)
    vgg_acs_model.summary()
    vgg_acs_model.fit(train_mri_data, train_behavioral_data, batch_size=4, epochs=1, validation_data=(test_mri_data, test_behavioral_data))

    print_results(
        [center_model, mean_model, median_model, simple_nn, vgg_acs_model], 
        test_mri_data, test_behavioral_data, [tf.keras.metrics.MeanSquaredError()])

    """
    model = VGG3DModel(output_units=behavioral_data.shape[1])
    model.compile(
		optimizer=model.optimizer,
		loss=model.loss,
		metrics=[],
	)
    model.build(mri_data.shape)
    model.summary()
    model.fit(train_mri_data, train_behavioral_data, batch_size=1, epochs=4, validation_data=(test_mri_data, test_behavioral_data))
    """


    """
    model = VGGSlicedModel(output_units=behavioral_data.shape[1])
    model.compile(
		optimizer=model.optimizer,
		loss=model.loss,
		metrics=[],
	)
    model.build(mri_data.shape)
    model.summary()
    model.fit(train_mri_data, train_behavioral_data, batch_size=1, epochs=4, validation_data=(test_mri_data, test_behavioral_data))
    """


if __name__ == "__main__":
    os.system("clear")
    main()