"""
Module Name: group_analysis.py
Description:
    This script demonstrates how to load and process surface data from Freesurfer outputs.
    It includes utilities for:
      - Extracting timestamps from file names
      - Extracting gradient and parcellation maps
      - Computing Dice coefficients
      - Performing correlations between parcel data

Author: Robin Junod, robin.junod@epfl.ch
Created: 2025-01-16

Usage:
    python group_analysis.py
"""

#%%
import os
import glob
from typing import Literal # Requires Python 3.8+
import numpy as np
import matplotlib.pyplot as plt
import nibabel as nib

from visualization import visualize_brain_surface
from smoothing import smooth_surface_graph
from watershed import watershed_by_flooding
from gradient import build_mesh_graph
from gradient import load_gradient_mgh
from watershed import load_labels_mgh



def extract_timestamp(fpath):
    fname = os.path.basename(fpath)  # e.g. "left_labels_20240101123045.mgh"
    # Split by "_" -> ["left", "labels", "20240101123045.mgh"]
    # The last part has "20240101123045.mgh"
    time_str = fname.split('_')[-1].replace(".mgh", "")
    return time_str

def extracrt_gradparc_list(hemisphere: Literal["lh", "rh"],
                           dataset_dir = r"D:\Data_Conn_Preproc\PPSFACE_N18"
                           ):
    list_parc = []
    list_grad = []
    for s in range(1,11): # (modify as needed)
        # print('grad map and parcellation map of subject : ', s)
        subject = f"{s:02d}"
        # Path to the subject directory (modify as needed)
        subj_dir = dataset_dir + r"\sub-" + subject
        grad_dir = subj_dir + r"\outputs_surface\gradient_map"
        parcel_dir = subj_dir + r"\outputs_surface\labels"
        pattern_grad = os.path.join(grad_dir, f"*_{hemisphere}_*.mgh")
        pattern_parc = os.path.join(parcel_dir, f"*_{hemisphere}_*.mgh")

        files_grad = glob.glob(pattern_grad)
        files_parc = glob.glob(pattern_parc)

        # Select latest files 
        files_grad_sorted = sorted(files_grad, key=lambda x: extract_timestamp(x))
        files_parc_sorted = sorted(files_parc, key=lambda x: extract_timestamp(x))

        latest_grad_file = files_grad_sorted[-1]
        latest_parc_file = files_parc_sorted[-1]
        
        # Add the data to the list 
        list_grad.append(load_gradient_mgh(latest_grad_file))
        
        # extract the boundary of the parcellation map
        parc_boundary = load_labels_mgh(latest_parc_file)
        list_parc.append(parc_boundary)
    
    gradient_list = np.stack(list_grad, axis=0)
    parcel_list = np.stack(list_parc, axis=0)
    return gradient_list, parcel_list


def extract_fmri_timeseries(hemisphere: Literal["lh", "rh"],
                            run = "1"):
    # Load all of the surf fmri data
    surf_fmri_list = []
    dataset_dir = r"D:\Data_Conn_Preproc\PPSFACE_N18"
    for i in range(1,11):
        subject = f"{i:02d}"
        subj_dir = dataset_dir + r"\sub-" + subject
        fmri_path = subj_dir + f"\\func\surf_conn_sub{subject}_run{run}_{hemisphere}.func.fsaverage6.mgh"
        surf_fmri_img = nib.load(fmri_path)
        surf_fmri = surf_fmri_img.get_fdata()
        surf_fmri = np.squeeze(surf_fmri) # just rearrange the MGH data
        # Normilize the data
        surf_fmri = (surf_fmri - np.mean(surf_fmri, axis=1, keepdims=True)) / np.std(surf_fmri, axis=1, keepdims=True)
        # Replace nan values with 0
        surf_fmri = np.nan_to_num(surf_fmri)
        surf_fmri_list.append(surf_fmri)
    return surf_fmri_list


def dice_coefficient(y_true, y_pred):
    """
    Compute the Dice coefficient between two binary masks.
    
    Args:
        y_true : (N,) ndarray
            Ground-truth binary mask.
        y_pred : (N,) ndarray
            Predicted binary mask.
    
    Returns:
        float : Dice coefficient.
    """
    # test the the inputs are 0,1 arrays
    assert np.array_equal(np.unique(y_true), [0, 1])
    assert np.array_equal(np.unique(y_pred), [0, 1])
    intersection = np.sum(y_true * y_pred)
    union = np.sum(y_true) + np.sum(y_pred)
    if union == 0:
        return 1.0
    return 2 * intersection / union

def homogeneity_craddock_rt(labels, 
                            list_surf_fmri_n):
    """They take every pair of voxels within an ROI and compute the Pearson correlation between the two voxels fMRI time series.
    The homogeneity for that ROI is then the average of these pairwise correlations
    
    Args:
        labels (np.ndarray): An array where each element indicates the parcel assignment 
                                   of the corresponding vertex in the surface fMRI data.
        list_surf_fmri_n (list): A list of 2D NORMALIZED arrays where each row represents a vertex and each column
                                    represents a time point of the fMRI data.
    Returns:
        float: The mean homogeneity score across all subjects and parcels.
    """
    homogeneity_sub = []
    for surf_fmri_n in list_surf_fmri_n: # average across all subjects
        # Get unique parcel indices greater than 0 (non-zero parcels)
        unique_parcels = np.unique(labels)
        unique_parcels = unique_parcels[unique_parcels >= 0]  # Avoid zero or background parcel
        # Initialize a list to store homogeneity scores for each parcel
        homogeneity_parc = []
        for parcel in unique_parcels: # average across all parcels
            # make a correaltion of the vertex in the parcel
            parcel_indices = np.where(labels == parcel)[0]
            homogeneity_parc.append(np.nan_to_num(np.corrcoef(surf_fmri_n[parcel_indices, :])).mean()) # Craddock homogenity
        homogeneity_sub.append(np.mean(homogeneity_parc))
    return np.mean(homogeneity_sub) # Return the mean homogenity across all subjects


def homogeneity_timecourse(group_parcel,
                        surf_fmri):
    from sklearn.decomposition import PCA
    """The homogeneity of a parcel represents the percent of variance in the parcel explained by 
       the most common connectivity pattern.
    
    Args:
        group_parcel (np.ndarray): An array where each element indicates the parcel assignment 
                                   of the corresponding vertex in the surface fMRI data.
        surf_fmri (np.ndarray): A 2D NORMALIZED array where each row represents a vertex and each column 
                                represents a time point of the fMRI data.
    Returns:
        list: A list of homogeneity scores for each parcel.
    """
    # Get unique parcel indices greater than 0 (non-zero parcels)
    unique_parcels = np.unique(group_parcel)
    unique_parcels = unique_parcels[unique_parcels > 0]  # Avoid zero or background parcel
    # Initialize a list to store homogeneity scores for each parcel
    homogeneity_scores = []
    for parcel in unique_parcels:
        # Extract the indices of vertices belonging to this parcel
        parcel_indices = np.where(group_parcel == parcel)[0]
        # Get the fMRI data for the vertices in the current parcel
        parcel_data = surf_fmri[parcel_indices, :]
        # Perform PCA on the parcel data
        pca = PCA(n_components=1)
        pca.fit(parcel_data)
        # The homogeneity is the variance explained by the first principal component
        explained_variance = pca.explained_variance_ratio_[0]
        # Store the homogeneity score for this parcel
        homogeneity_scores.append(explained_variance)
    
    # transform the homogeneity scores to a numpy array
    homogeneity_scores = np.array(homogeneity_scores)
    # keep the mean homogeneity score
    homogeneity_mean = np.mean(homogeneity_scores)
    return homogeneity_mean




def parcel_correlation(group_parcel, 
                       surf_fmri):
    """
    Group the fMRI data into parcels and compute the correlation between parcels.
        group_parcel (np.ndarray): An array where each element indicates the parcel assignment 
                                   of the corresponding vertex in the surface fMRI data.
        surf_fmri (np.ndarray): Single Subject fmri data, A 2D array where each row represents a vertex and each column 
                                represents a time point of the fMRI data.
    Returns:
        np.ndarray: A 2D array representing the correlation matrix between the parcels.
    """
    # Get unique parcel indices greater than 0 (non-zero parcels)
    parcel_idx = np.unique(group_parcel[group_parcel >= 0])
    n_parcels = len(parcel_idx)
    
    # Initialize an array to store mean fMRI data for each parcel
    parcel_data = np.zeros((n_parcels, surf_fmri.shape[1]))
    
    # For each parcel, calculate the mean fMRI time series across vertices in the parcel
    for i, idx in enumerate(parcel_idx):
        # Boolean mask for vertices in the current parcel
        mask = group_parcel == idx
        # Compute the mean fMRI data for this parcel and store it
        parcel_data[i] = np.mean(surf_fmri[mask], axis=0)
        
        # Check for NaN values in the computed parcel data
        if np.isnan(parcel_data[i]).any():
            print(f'Parcel {idx} has NaN values')
    
    # Compute and return the correlation matrix between parcels
    parcel_corr = np.corrcoef(parcel_data)
    return parcel_corr


def hierarchical_corr_mtrx(corr_matrix, show=True):
    import scipy.cluster.hierarchy as sch
    # Compute the linkage matrix
    linkage_matrix = sch.linkage(corr_matrix, method='ward')
    dendrogram = sch.dendrogram(linkage_matrix, no_plot=True)
    cluster_idxs = dendrogram['leaves']
    # Reorder the correlation matrix
    reordered_corr_matrix = corr_matrix[np.ix_(cluster_idxs, cluster_idxs)]
    if show:
        import seaborn as sns
        # Plot the reordered correlation matrix
        plt.figure(figsize=(10, 8))
        sns.heatmap(reordered_corr_matrix, cmap="coolwarm", square=True)
        plt.title('Reordered Parcel Correlation Matrix')
        plt.show()
    return reordered_corr_matrix



from collections import deque
def create_random_parcels(graph, n_clusters):
    """
    Randomly cluster a connected graph using BFS with 140 seeds.
    
    Args:
        graph: dict[int, list[int]]
            Adjacency list representation of the graph.
            Keys are vertex IDs, values are lists of neighbors.
        n_clusters: int
            Number of clusters to grow.
    
    Returns:
        labels: np.ndarray
            Array of shape (n_vertices,) with cluster labels:
            -1 = unassigned
            -2 = boundary
            >= 0 = cluster ID
    """
    n_vertices = len(graph)
    labels = np.full(n_vertices, -1, dtype=int)  # Initialize all vertices as unassigned
    # Step 1: Randomly select seeds
    seeds = np.random.choice(n_vertices, size=n_clusters, replace=False)
    for cluster_id, seed in enumerate(seeds):
        labels[seed] = cluster_id  # Assign each seed a unique cluster ID

    # Step 2: Initialize queues for BFS
    queues = [deque([seed]) for seed in seeds]

    # Step 3: BFS Growth
    while any(queues):  # While any cluster is still growing
        for cluster_id, queue in enumerate(queues):
            if not queue:
                continue  # Skip if this cluster's queue is empty
            current_vertex = queue.popleft()  # Get the next vertex to process
            
            # Iterate over neighbors of the current vertex
            for neighbor in graph[current_vertex]:
                if labels[neighbor] == -1:  # If the neighbor is unassigned
                    labels[neighbor] = cluster_id  # Assign the current cluster ID
                    queue.append(neighbor)  # Add the neighbor to the queue
                elif labels[neighbor] >= 0 and labels[neighbor] != cluster_id:
                    # Conflict: Neighbor belongs to a different cluster
                    labels[current_vertex] = -2  # Mark the current vertex as a boundary
                    labels[neighbor] = -2        # Mark the neighbor as a boundary

    return labels




#%% TODO : try to perform watershed on gradient and on parcels
if __name__ == "__main__":
    import nibabel as nib
    # surface_path = r"D:\DATA_min_preproc\dataset_study1\fsaverage6\surf\lh.white"
    surface_path = r"D:\DATA_min_preproc\dataset_PPSFace1\fsaverage6\surf\lh.inflated"
    coords, faces = nib.freesurfer.read_geometry(surface_path)
    graph = build_mesh_graph(faces)
    
    # Load all of the surf fmri data
    surf_fmri_list = extract_fmri_timeseries(hemisphere='lh')
    # Load the gradient and parcellation maps
    gradient_list, parcel_list = extracrt_gradparc_list(hemisphere='lh')

    visualize_brain_surface(coords, faces, gradient_list[0], title="Group Gradient")
    
    # Compute group parcellation
    group_gradient = gradient_list.mean(axis=0)
    group_gradient_smoothed = smooth_surface_graph(graph, group_gradient,  iterations=10)
    visualize_brain_surface(coords, faces, group_gradient_smoothed, title="Group Gradient")
    
    # Labels the group gradient map
    group_parc = watershed_by_flooding(graph, group_gradient_smoothed)
    group_boundary = (group_parc<0)*1
    visualize_brain_surface(coords, faces, group_boundary, title="Group Bounardy")
    
    # Compute dice coefficient with the boundaries
    dice_coef_list = []
    for i in range(18):
        subj_boundary = 1*(parcel_list[i]<0)
        dice = dice_coefficient(group_boundary, subj_boundary)
        dice_coef_list.append(dice)
        print(f"Subject {i+1} Dice coefficient: {dice}")
        
    # Compare group dice coefficient
    groupA_mean = gradient_list[:8,:].mean(axis=0)
    groupA_mean = smooth_surface_graph(graph, groupA_mean,  iterations=10)
    groupA_parc = watershed_by_flooding(graph, groupA_mean)
    groupA_boundary = (groupA_parc<0)*1
    groupB_mean = gradient_list[8:,:].mean(axis=0)
    groupB_mean = smooth_surface_graph(graph, groupB_mean,  iterations=10)
    groupB_parc = watershed_by_flooding(graph, groupB_mean)
    groupB_boundary = (groupB_parc<0)*1
    
    

    #%% Compute the corr between parcels
    sub1_parccorr = parcel_correlation(group_parc, surf_fmri_list[9])
    reordered_corr_matrix = hierarchical_corr_mtrx(sub1_parccorr, show=True)

    #%% Select a cluster of interest
    # new_to_original = {new_idx: original_idx for new_idx, original_idx in enumerate(cluster_idxs)}
    # # Custom the range of interest
    # new_to_original_range = [new_to_original[new_idx] for new_idx in range(70, 88 + 1) if new_idx in new_to_original]
    # parc_network = np.isin(group_parc, new_to_original_range)*1 # 1 if in the cluster, 0 otherwise
    # visualize_brain_surface(coords, faces, parc_network, title="Parcel Network")



# %%
