import tensorflow as tf
from keras.layers import Input, LSTM, Dense, Dropout, Lambda
from keras.models import Model, load_model
from keras.callbacks import ModelCheckpoint
from keras.layers.merge import Concatenate
from collections import deque
from tqdm import tqdm
import argparse

from constants import SEQUENCE_LENGTH
from dataset import *
from music import OCTAVE
from midi_util import midi_encode
import midi

def f1_score(actual, predicted):
    # F1 score statistic
    # Count true positives, true negatives, false positives and false negatives.
    tp = tf.count_nonzero(predicted * actual, dtype=tf.float32)
    tn = tf.count_nonzero((predicted - 1) * (actual - 1), dtype=tf.float32)
    fp = tf.count_nonzero(predicted * (actual - 1), dtype=tf.float32)
    fn = tf.count_nonzero((predicted - 1) * actual, dtype=tf.float32)

    # Calculate accuracy, precision, recall and F1 score.
    accuracy = (tp + tn) / (tp + fp + fn + tn)
    # Prevent divide by zero
    zero = tf.constant(0, dtype=tf.float32)
    precision = tf.cond(tf.not_equal(tp, 0), lambda: tp / (tp + fp), lambda: zero)
    recall = tf.cond(tf.not_equal(tp, 0), lambda: tp / (tp + fn), lambda: zero)
    pre_f = 2 * precision * recall
    fmeasure = tf.cond(tf.not_equal(pre_f, 0), lambda: pre_f / (precision + recall), lambda: zero)
    return fmeasure

def build_model():
    notes_in = Input((SEQUENCE_LENGTH, NUM_NOTES))
    # Target input for conditioning
    targets_in = Input((SEQUENCE_LENGTH, NUM_NOTES))

    """ Time axis """
    # Pad note by one octave
    x = Dropout(0.2)(notes_in)
    pad_note_layer = Lambda(lambda x: tf.pad(x, [[0, 0], [0, 0], [OCTAVE, OCTAVE]]), name='padded_note_in')
    padded_notes = pad_note_layer(x)
    time_axis_rnn = LSTM(256, return_sequences=True, activation='tanh', name='time_axis_rnn')
    time_axis_outs = []

    for n in range(OCTAVE, NUM_NOTES + OCTAVE):
        # Input one octave of notes
        octave_in = Lambda(lambda x: x[:, :, n - OCTAVE:n + OCTAVE + 1], name='note_' + str(n))(padded_notes)
        time_axis_out = time_axis_rnn(octave_in)
        time_axis_outs.append(time_axis_out)
    out = Concatenate()(time_axis_outs)

    out = Dropout(0.5)(out)

    # Shift target one note to the left.
    shift_target = Lambda(lambda x: tf.pad(x[:, :, :-1], [[0, 0], [0, 0], [1, 0]]))(targets_in)

    """ Prediction Layer """
    prediction_layer = Dense(NUM_NOTES, activation='sigmoid')
    predictions = prediction_layer(out)

    model = Model(notes_in, predictions)
    model.compile(optimizer='adam', loss='binary_crossentropy', metrics=['acc'])
    return model

def main():
    parser = argparse.ArgumentParser(description='Generates music.')
    parser.add_argument('--train', default=False, action='store_true', help='Train model?')
    args = parser.parse_args()

    if args.train:
        print('Training')
        train()
    else:
        print('Generating')
        results = generate()
        mf = midi_encode(unclamp_midi(results))
        midi.write_midifile('out/result.mid', mf)

def build_or_load():
    model = build_model()
    try:
        model.load_weights('out/model.h5')
        print('Loaded model from file.')
    except:
        print('Unable to load model from file.')
    model.summary()
    return model

def train():
    train_data, train_labels = load_all(['data/baroque'], BATCH_SIZE, SEQUENCE_LENGTH)

    model = build_or_load()

    cbs = [ModelCheckpoint('out/model.h5', monitor='loss', save_best_only=True)]
    model.fit(train_data, train_labels, epochs=1000, callbacks=cbs)

def generate():
    model = build_or_load()

    notes_memory = deque([np.zeros(NUM_NOTES) for _ in range(SEQUENCE_LENGTH)], maxlen=SEQUENCE_LENGTH)
    results = []

    def make_batch():
        return np.array([notes_memory])

    for t in tqdm(range(NOTES_PER_BAR * 4)):
        # The next note being built.
        next_note = np.zeros(NUM_NOTES)

        for n in range(NUM_NOTES):
            predictions = model.predict(make_batch())
            # We only care about the last time step
            prob = predictions[0][-1]
            # Flip on randomly
            next_note[n] = 1 if np.random.random() <= prob[n] else 0

        notes_memory.append(next_note)
        results.append(next_note)

    return results

if __name__ == '__main__':
    main()
